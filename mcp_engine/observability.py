"""Phoenix/OpenTelemetry observability helpers for SideQuests.

This module is intentionally defensive:
- observability is disabled by default
- missing Phoenix/OTel dependencies degrade to a no-op backend
- redaction is the default behavior for string-heavy payloads
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Optional, ContextManager, Iterator


logger = logging.getLogger(__name__)

_SENSITIVE_KEY_FRAGMENTS = {
    "content",
    "prompt",
    "query",
    "reasoning",
    "rationale",
    "text",
    "api_key",
    "secret",
    "password",
    "token",
}
_BULKY_KEY_FRAGMENTS = {
    "frame",
    "grid",
    "pattern",
    "image",
    "pixels",
    "data",
}


def _redact_value(key: str, value: Any) -> Any:
    """Redact sensitive or bulky values for observability."""
    if not isinstance(value, str):
        return value

    lower_key = key.lower()
    
    # Check for sensitive keys
    if any(frag in lower_key for frag in _SENSITIVE_KEY_FRAGMENTS):
        if not value:
            return value
        # SHA-256 prefix + [redacted]
        h = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
        return f"{h}:[redacted]"

    # Check for bulky keys
    if any(frag in lower_key for frag in _BULKY_KEY_FRAGMENTS):
        if len(value) > 100:
            return f"[{len(value)} chars]"

    return value


def _redact_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Redact a dictionary of attributes."""
    return {k: _redact_value(k, v) for k, v in attributes.items()}


@dataclass
class _SpanContext:
    name: str
    attributes: dict[str, Any]
    start_time: float = field(default_factory=time.monotonic)


class Span(ContextManager):
    """A span context manager that supports both 'with' and direct enter/exit."""
    
    def __init__(self, name: str, attributes: dict[str, Any], observability: Observability):
        self.name = name
        self.attributes = _redact_attributes(attributes)
        self.observability = observability
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def __enter__(self) -> Span:
        self.start_time = time.monotonic()
        # In a real implementation with OTel, we would start a span here.
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.monotonic()
        elapsed_ms = (self.end_time - self.start_time) * 1000
        
        if self.observability.enabled:
            # If enabled, we could log the span to the backend.
            # For now, we forward it to emit_structured_event if it was a top-level span
            # or handle it via the backend if Phoenix is present.
            pass
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = _redact_value(key, value)


class Observability:
    def __init__(self, *, enabled: bool, backend: Any = None):
        self._enabled = enabled
        self._backend = backend

    @property
    def enabled(self) -> bool:
        return self._enabled

    def span(self, name: str, attributes: dict[str, Any]) -> ContextManager:
        if not self._enabled:
            return contextlib.nullcontext()
        return Span(name, attributes, self)

    def emit_structured_event(
        self, 
        event_type: str, 
        operation: str, 
        details: Optional[dict] = None, 
        result: Optional[dict] = None, 
        elapsed_ms: Optional[float] = None
    ) -> None:
        if not self._enabled:
            return
        
        # Redact details and result
        redacted_details = _redact_attributes(details or {})
        redacted_result = _redact_attributes(result or {})
        
        # If we have a backend (Phoenix), we would log it there.
        # This is a simplified implementation.
        if self._backend:
            try:
                # In a real scenario, this might call phoenix.trace or similar.
                pass
            except Exception:
                logger.debug("Failed to emit event to Phoenix", exc_info=True)


def canonical_span_name(operation: str) -> str:
    """Prepend 'sidequests.' to the operation name."""
    return f"sidequests.{operation}"


def build_observability(config: dict) -> Observability:
    """Build an Observability instance based on config and availability."""
    if not isinstance(config, dict):
        return Observability(enabled=False)
    
    obs_cfg = config.get("observability", {})
    if not obs_cfg.get("enabled"):
        return Observability(enabled=False)
    
    try:
        import phoenix
        # In a real setup, we might also initialize phoenix here:
        # phoenix.launch_app() 
        return Observability(enabled=True, backend=phoenix)
    except ImportError:
        return Observability(enabled=False)
