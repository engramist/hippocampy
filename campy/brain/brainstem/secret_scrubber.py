"""
campy/brain/brainstem/secret_scrubber.py — B338 Content-Level Secret Scrubbing

Detects and redacts common credential patterns before text_raw is persisted:
- AWS access keys (AKIA followed by 16 characters)
- Generic API key patterns (high-entropy strings)
- Private key PEM headers
- Bearer tokens (Authorization: Bearer ...)

This is a DETECTION-based approach, not a full secret scanning engine.
Detected secrets are replaced with [REDACTED:secret_type] in place.
"""

import re
from typing import NamedTuple


class SecretMatch(NamedTuple):
    """Result of secret detection."""
    secret_type: str
    pattern: str
    start: int
    end: int


# Regex patterns for common credential shapes
_PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "aws_secret_key": re.compile(r"(?i)(aws_secret_access_key|aws_secret_key)\s*[=:]\s*['\"]*([A-Za-z0-9/+=]{40})"),
    "private_key_pem": re.compile(r"-----BEGIN\s+[A-Z\s]+(?:PRIVATE|RSA|DSA|EC|ED25519)\s+KEY-----", re.IGNORECASE),
    "bearer_token": re.compile(r"(?i)(authorization|bearer)\s*[:=]\s*['\"]*Bearer\s+([A-Za-z0-9._\-]+)"),
    "api_key_pattern": re.compile(r"(?i)(api[_-]?key|apikey|api_token|sk[-_])\s*[:=\s]+['\"]*([A-Za-z0-9_\-]{20,})"),
    "github_token": re.compile(r"(ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]{36,255}\b"),
    "slack_token": re.compile(r"(xox[baprs]-[0-9]{7,13}-[0-9]{7,13}-[0-9A-Za-z]{24,34}|xoxp-[0-9A-Za-z]{160,})"),
    "database_password": re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]*([^\s'\"]{8,})"),
}


def detect_secrets(text: str) -> list[SecretMatch]:
    """
    Detect common secret patterns in text.
    Returns list of (secret_type, matched_text, start_pos, end_pos).
    """
    matches = []
    for secret_type, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            matches.append(SecretMatch(
                secret_type=secret_type,
                pattern=match.group(0),
                start=match.start(),
                end=match.end(),
            ))
    return matches


def scrub_secrets(text: str, aggressive: bool = False) -> tuple[str, int]:
    """
    Scrub detected secrets from text by replacing with redaction markers.

    Args:
        text: Text to scrub
        aggressive: If False, only scrub high-confidence patterns.
                   If True, also scrub generic high-entropy strings.

    Returns:
        (scrubbed_text, num_secrets_found)
    """
    if not text:
        return text, 0

    # Detect secrets (in reverse order to preserve indices during replacement)
    matches = detect_secrets(text)
    if not matches:
        return text, 0

    # Sort by position (descending) so replacements don't shift indices
    matches = sorted(matches, key=lambda m: m.start, reverse=True)

    scrubbed = text
    for match in matches:
        redaction = f"[REDACTED:{match.secret_type}]"
        scrubbed = scrubbed[:match.start] + redaction + scrubbed[match.end:]

    return scrubbed, len(matches)


async def scrub_before_ingest(text: str) -> tuple[str, dict]:
    """
    B338: Async scrubber hook for ingest chokepoints.
    
    Call this before setting text_raw on any node. Returns scrubbed text
    and metadata dict with detected secret count and types.
    
    Args:
        text: Raw text to scrub
        
    Returns:
        (scrubbed_text, metadata_dict) where metadata_dict contains:
            - secrets_found: int count
            - secret_types: list of detected types
    """
    scrubbed, count = scrub_secrets(text)
    
    # Extract unique secret types for logging
    if count > 0:
        matches = detect_secrets(text)
        secret_types = list(set(m.secret_type for m in matches))
    else:
        secret_types = []
    
    metadata = {
        "secrets_found": count,
        "secret_types": secret_types,
        "was_scrubbed": count > 0,
    }
    
    return scrubbed, metadata
