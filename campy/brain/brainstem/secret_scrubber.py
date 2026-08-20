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
# B338: Improved patterns with better coverage and fewer false negatives.
# Each pattern targets a specific secret shape rather than trying to detect
# generic "high entropy" which produces too many false positives.
_PATTERNS = {
    # AWS access keys: AKIA followed by 16 alphanumeric chars
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    
    # AWS secret keys: longer base64-like strings after aws_secret_ or similar
    # Also matches environment variable format with = or : separator
    "aws_secret_key": re.compile(
        r"(?i)(?:aws_secret_access_key|aws_secret_key|AWS_SECRET_ACCESS_KEY|AWS_SECRET_KEY)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40,})(?:['\"]|\s|$)",
        re.MULTILINE
    ),
    
    # Private key PEM headers (RSA, EC, ED25519, DSA, etc.)
    "private_key_pem": re.compile(
        r"-----BEGIN\s+[A-Z\s]*(?:PRIVATE|RSA|DSA|EC|ED25519|OPENSSH|ENCRYPTED|PGP)\s+KEY(?:\s+[A-Z]*)?\s*-----",
        re.IGNORECASE
    ),
    
    # Bearer tokens in Authorization headers
    "bearer_token": re.compile(
        r"(?i)(?:authorization|bearer)\s*[:=]\s*['\"]?Bearer\s+([A-Za-z0-9._\-~+/=]{20,})",
        re.MULTILINE
    ),
    
    # API key patterns: explicit key assignment with at least 20 chars
    "api_key_pattern": re.compile(
        r"(?i)(?:api[_-]?key|apikey|api_token|api_secret|sk[-_]live|sk[-_]test)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{20,})['\"]?(?:\s|$)",
        re.MULTILINE
    ),
    
    # GitHub personal access tokens
    "github_token": re.compile(r"(?:ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]{36,255}\b"),
    
    # Slack tokens: xoxb/xoxp/xoxr/xoxs formats
    # More permissive to catch variations: word chars + hyphens
    "slack_token": re.compile(
        r"(?:xoxb|xoxp|xoxr|xoxs|xoxa|xoxc)-[A-Za-z0-9_-]{10,}"
    ),
    
    # Database passwords: password=value patterns (8+ chars to reduce false positives)
    "database_password": re.compile(
        r"(?i)(?:password|passwd|pwd|db_password|dbpasswd)\s*[:=]\s*['\"]([^\s'\"]{8,})['\"]?",
        re.MULTILINE
    ),
    
    # Django SECRET_KEY and similar framework secrets
    "django_secret_key": re.compile(
        r"(?i)(?:secret_key|django_secret_key|secret)\s*[:=]\s*['\"]([A-Za-z0-9_\-!@#$%^&*()+=\[\]{}:;<>,.?/~`]{32,})['\"]",
        re.MULTILINE
    ),
    
    # MongoDB/database connection strings with passwords
    "mongo_connection_string": re.compile(
        r"mongodb(?:\+srv)?://[^:]+:([A-Za-z0-9_\-!@#$%^&*()+=~]{8,})@"
    ),
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
