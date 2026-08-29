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

TOOL_PERMISSIONS = {
    "knowledge_search": {Role.VIEWER, Role.ANALYST, Role.ADMIN},
    "python_analysis": {Role.ANALYST, Role.ADMIN},
    "enterprise_mcp": {Role.ANALYST, Role.ADMIN},
    "admin_reindex": {Role.ADMIN},
}


def validate_prompt(text: str) -> None:
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in INJECTION_PATTERNS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request rejected by prompt-injection protection",
        )


def authorize_tool(user: User, tool: str) -> None:
    if user.role not in TOOL_PERMISSIONS.get(tool, set()):
        raise HTTPException(status_code=403, detail=f"Role '{user.role}' cannot use {tool}")


def filter_evidence(user: User, evidence: list[Evidence]) -> list[Evidence]:
    return [item for item in evidence if item.metadata.get("access_level", "internal") in user.access_levels]


def validate_citations(answer: str, evidence: list[Evidence]) -> tuple[bool, list[str]]:
    cited = set(re.findall(r"\[([\w-]+)\]", answer))
    allowed = {item.document_id for item in evidence}
    invalid = sorted(cited - allowed)
    return not invalid, invalid


@dataclass
class Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.buckets: dict[str, Bucket] = {}
        self.lock = Lock()

    def consume(self, user_id: str, cost: float = 1) -> None:
        now = time.monotonic()
        with self.lock:
            bucket = self.buckets.setdefault(
                user_id, Bucket(float(self.settings.rate_limit_capacity), now)
            )
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
