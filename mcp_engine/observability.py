"""Phoenix/OpenTelemetry observability helpers for SideQuests."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import sys
from dataclasses import dataclass
from typing import Any, ContextManager, Optional

logger = logging.getLogger(__name__)

REQUIRED_DECISION_FIELDS = ("session_id", "task_id", "step", "phase", "action_id")
REQUIRED_OUTCOME_FIELDS = ("session_id", "task_id", "step", "phase", "state_after")

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
    "payload",
    "request",
    "response",
    "data",
}


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _redact_value(key: str, value: Any, mode: str = "redacted") -> Any:
    lower_key = key.lower()
    mode = str(mode or "redacted").lower()
    in_debug_mode = mode in {"verbose", "debug", "full"}
    max_text = 2000 if in_debug_mode else 300

    if isinstance(value, str):
        # Never expose raw credentials even in debug mode.
        if any(frag in lower_key for frag in {"api_key", "secret", "password", "token"}):
            if not value:
                return value
            h = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
            return f"{h}:[redacted]"
        if any(frag in lower_key for frag in _SENSITIVE_KEY_FRAGMENTS):
            if in_debug_mode:
                return _truncate_text(value, max_text)
            if not value:
                return value
            h = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
            return f"{h}:[redacted]"
        if any(frag in lower_key for frag in _BULKY_KEY_FRAGMENTS) and len(value) > 100:
            return f"[{len(value)} chars]"
        return _truncate_text(value, max_text)
    if isinstance(value, (list, tuple)):
        if in_debug_mode and all(isinstance(x, (str, int, float, bool, type(None))) for x in value[:20]):
            return str(list(value[:20]))
        if value and isinstance(value[0], list):
            rows = len(value)
            cols = len(value[0]) if rows and isinstance(value[0], list) else 0
            return f"[matrix {rows}x{cols}]"
        return str(value[:8]) if len(value) > 8 else str(value)
    if isinstance(value, dict):
        if in_debug_mode:
            compact = {str(k): v for k, v in list(value.items())[:30]}
            return str(compact)
        if any(frag in lower_key for frag in _BULKY_KEY_FRAGMENTS):
            keys = ",".join(sorted(str(k) for k in list(value.keys())[:8]))
            return f"[object keys={keys}]"
        return str(value)
    return value


def _redact_attributes(attributes: dict[str, Any], mode: str = "redacted") -> dict[str, Any]:
    return {k: _redact_value(k, v, mode=mode) for k, v in attributes.items()}


class Span(ContextManager):
    """Span wrapper that supports explicit enter/exit usage."""

    def __init__(self, name: str, attributes: dict[str, Any], observability: "Observability"):
        self.name = name
        self.attributes = _redact_attributes(attributes, mode=observability.mode)
        self._obs = observability
        self._ctx = None
        self._span = None
        self._active = False

    def __enter__(self) -> "Span":
        if not self._obs.enabled or self._obs._tracer is None:
            return self
        self._ctx = self._obs._tracer.start_as_current_span(self.name)
        self._span = self._ctx.__enter__()
        if self.attributes:
            self._span.set_attributes(self.attributes)
        self._active = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if not self._active or self._ctx is None:
            return False
        try:
            if exc_val and self._span is not None:
                self._span.record_exception(exc_val)
        finally:
            self._ctx.__exit__(exc_type, exc_val, exc_tb)
            self._active = False
        return False

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        if not self._active or self._span is None:
            return
        self._span.set_attributes(_redact_attributes(attributes, mode=self._obs.mode))

    def set_attribute(self, key: str, value: Any) -> None:
        """Compatibility shim for call sites using OTel's singular helper."""
        self.set_attributes({key: value})

    def add_event(self, name: str, attributes: Optional[dict[str, Any]] = None) -> None:
        if not self._active or self._span is None:
            return
        self._span.add_event(name, _redact_attributes(attributes or {}, mode=self._obs.mode))

    def record_exception(self, exc: BaseException, attributes: Optional[dict[str, Any]] = None) -> None:
        if not self._active or self._span is None:
            return
        self._span.record_exception(exc)
        if attributes:
            self._span.set_attributes(_redact_attributes(attributes, mode=self._obs.mode))


@dataclass(init=False)
class Observability:
    _enabled: bool
    _tracer: Any = None
    mode: str = "redacted"

    def __init__(
        self,
        _enabled: bool = False,
        _tracer: Any = None,
        mode: str = "redacted",
        enabled: Optional[bool] = None,
    ):
        # Backward compatibility: some tests/callers pass `enabled=...`.
        if enabled is not None:
            _enabled = bool(enabled)
        self._enabled = bool(_enabled)
        self._tracer = _tracer
        self.mode = mode

    @property
    def enabled(self) -> bool:
        return bool(self._enabled)

    def span(self, name: str, attributes: dict[str, Any]) -> ContextManager:
        if not self.enabled:
            return contextlib.nullcontext()
        return Span(name, attributes, self)

    def emit_structured_event(
        self,
        event_type: str,
        operation: str,
        details: Optional[dict] = None,
        result: Optional[dict] = None,
        elapsed_ms: Optional[float] = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            from opentelemetry import trace

            current = trace.get_current_span()
            if current is None:
                return
            attrs = {
                "event_type": event_type,
                "operation": operation,
            }
            if elapsed_ms is not None:
                attrs["elapsed_ms"] = float(elapsed_ms)
            if details:
                attrs.update(_redact_attributes({f"details.{k}": v for k, v in details.items()}, mode=self.mode))
            if result:
                attrs.update(_redact_attributes({f"result.{k}": v for k, v in result.items()}, mode=self.mode))
            current.add_event(canonical_span_name(operation), attrs)
        except Exception:
            logger.debug("Failed to emit structured event", exc_info=True)

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            from opentelemetry import trace

            current = trace.get_current_span()
            if current is None:
                return
            current.set_attributes(_redact_attributes(attributes, mode=self.mode))
        except Exception:
            logger.debug("Failed to set span attributes", exc_info=True)


def canonical_span_name(operation: str) -> str:
    if "." in operation:
        return operation
    if operation.startswith("sidequests."):
        return operation
    return f"sidequests.{operation}"


def ensure_contract_fields(
    attrs: dict[str, Any],
    required_fields: tuple[str, ...],
    *,
    strict: bool = False,
    defaults: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Ensure required telemetry fields exist; optionally raise when missing."""
    out = dict(attrs or {})
    defaults = defaults or {}
    missing: list[str] = []
    for key in required_fields:
        val = out.get(key)
        if val is None or val == "":
            if key in defaults:
                out[key] = defaults[key]
            else:
                missing.append(key)
    if missing and strict:
        raise ValueError(f"Missing required telemetry fields: {', '.join(sorted(missing))}")
    return out


def build_observability(config: dict) -> Observability:
    if not isinstance(config, dict):
        return Observability(_enabled=False)

    obs_cfg = config.get("observability", {}) or {}
    if not obs_cfg.get("enabled"):
        return Observability(_enabled=False)

    backend = str(obs_cfg.get("backend", "phoenix")).lower()
    if backend != "phoenix":
        logger.warning("Unsupported observability backend '%s'; disabling.", backend)
        return Observability(_enabled=False)

    endpoint = str(obs_cfg.get("endpoint", "http://127.0.0.1:6006/v1/traces"))
    project_name = str(obs_cfg.get("project_name", "sidequests-arc"))
    mode = str(obs_cfg.get("mode", "redacted")).lower()
    strict = bool(obs_cfg.get("strict_startup_check", True))

    # Prefer phoenix.otel if installed.
    try:
        from phoenix.otel import register

        tracer_provider = register(
            project_name=project_name,
            endpoint=endpoint,
            protocol="http/protobuf",
            auto_instrument=False,
            batch=False,
        )
        tracer = tracer_provider.get_tracer("sidequests-brain")
        logger.info("Observability enabled via phoenix.otel (project=%s, endpoint=%s)", project_name, endpoint)
        return Observability(_enabled=True, _tracer=tracer, mode=mode)
    except Exception:
        logger.debug("phoenix.otel registration unavailable; trying raw OTLP exporter", exc_info=True)

    # Fallback: raw OTLP exporter.
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        resource = Resource.create(
            {
                "service.name": "sidequests-brain",
                "phoenix.project_name": project_name,
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("sidequests-brain")
        logger.info("Observability enabled via raw OTLP exporter (project=%s, endpoint=%s)", project_name, endpoint)
        return Observability(_enabled=True, _tracer=tracer, mode=mode)
    except Exception:
        msg = (
            "Observability startup failed while enabled.\n"
            f"python_executable={sys.executable}\n"
            f"project_name={project_name}\n"
            f"endpoint={endpoint}\n"
            "Install tracing dependencies in this interpreter "
            "(opentelemetry + phoenix/arize-phoenix-otel) or disable [observability].enabled."
        )
        if strict:
            raise RuntimeError(msg)
        logger.warning(msg)
        logger.debug("Observability initialization failed (soft-fail mode)", exc_info=True)
        return Observability(_enabled=False)
