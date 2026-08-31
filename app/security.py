"""Deterministic security controls for prompts, tools, evidence, outputs, and quotas."""

import re
import time
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException, status

from app.config import get_settings
from app.models import Evidence, Role, User

INJECTION_PATTERNS = [
    r"ignore (all|any|the|previous) instructions",
    r"reveal (the )?(system|developer) prompt",
    r"(?:print|show|export|exfiltrate).*(?:secret|credential|api key|password)",
    r"bypass (?:authorization|rbac|security)",
]

SENSITIVE_OUTPUT_PATTERNS = [
    r"\b(?:api[_ -]?key|client[_ -]?secret|password)\s*[:=]\s*\S+",
    r"\bsk-[A-Za-z0-9_-]{16,}\b",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]

TOOL_PERMISSIONS = {
    "knowledge_search": {Role.VIEWER, Role.ANALYST, Role.ADMIN},
    "python_analysis": {Role.ANALYST, Role.ADMIN},
    "enterprise_mcp": {Role.ANALYST, Role.ADMIN},
    "admin_reindex": {Role.ADMIN},
}


def validate_prompt(text: str) -> None:
    """Reject common instruction override, exfiltration, and authorization bypass requests."""

    if any(re.search(pattern, text, re.IGNORECASE) for pattern in INJECTION_PATTERNS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request rejected by prompt-injection protection",
        )


def sanitize_retrieved_text(text: str) -> str:
    """Remove instruction-like lines from untrusted documents before model context assembly."""
    # Scan line-by-line to preserve useful document evidence around a malicious instruction.
    safe_lines = []
    for line in text.splitlines():
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in INJECTION_PATTERNS):
            safe_lines.append("[potential embedded instruction removed]")
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines)


def validate_sensitive_output(text: str) -> bool:
    """Return false when generated output resembles a credential or private key."""
    return not any(re.search(pattern, text, re.IGNORECASE) for pattern in SENSITIVE_OUTPUT_PATTERNS)


def authorize_tool(user: User, tool: str) -> None:
    """Enforce RBAC at the tool boundary, independently of model-generated decisions."""

    if user.role not in TOOL_PERMISSIONS.get(tool, set()):
        raise HTTPException(status_code=403, detail=f"Role '{user.role}' cannot use {tool}")


def filter_evidence(user: User, evidence: list[Evidence]) -> list[Evidence]:
    """Remove evidence above the caller's access level before it reaches an LLM."""

    return [item for item in evidence if item.metadata.get("access_level", "internal") in user.access_levels]


def validate_citations(answer: str, evidence: list[Evidence]) -> tuple[bool, list[str]]:
    """Detect document IDs in an answer that were not supplied as authorized evidence."""

    # Compare model output against IDs from this request, never against the global corpus.
    cited = set(re.findall(r"\[([\w-]+)\]", answer))
    allowed = {item.document_id for item in evidence}
    invalid = sorted(cited - allowed)
    return not invalid, invalid


@dataclass
class Bucket:
    """Mutable token balance and monotonic timestamp for one user."""

    tokens: float
    updated_at: float


class TokenBucketLimiter:
    """Thread-safe, per-user token bucket with configurable refill behavior."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.buckets: dict[str, Bucket] = {}
        self.lock = Lock()

    def consume(self, user_id: str, cost: float = 1) -> None:
        """Consume quota or raise a graceful HTTP 429 with a retry hint."""

        # Monotonic time is immune to wall-clock corrections that could corrupt refill math.
        now = time.monotonic()
        with self.lock:
            bucket = self.buckets.setdefault(
                user_id, Bucket(float(self.settings.rate_limit_capacity), now)
            )
            # Refill lazily on access instead of running one timer task per authenticated user.
            elapsed = now - bucket.updated_at
            bucket.tokens = min(
                self.settings.rate_limit_capacity,
                bucket.tokens + elapsed * self.settings.rate_limit_refill_per_second,
            )
            bucket.updated_at = now
            if bucket.tokens < cost:
                retry = (cost - bucket.tokens) / self.settings.rate_limit_refill_per_second
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(max(1, int(retry)))},
                )
            bucket.tokens -= cost


rate_limiter = TokenBucketLimiter()
