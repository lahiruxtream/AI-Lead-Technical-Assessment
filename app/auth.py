"""HTTP Basic authentication and local role assignment for assessment users."""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings
from app.models import Role, User

security = HTTPBasic()


@dataclass(frozen=True)
class UserRecord:
    """Bind a stored password derivation to its immutable domain user."""

    password_hash: str
    user: User


_PBKDF2_ITERATIONS = 600_000


def _hash(password: str, username: str) -> str:
    """Slow, salted password derivation suitable for the assessment's local accounts."""
    # Username-derived salts make identical demo passwords produce different stored values.
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), f"enterprise-assistant:{username}".encode(), _PBKDF2_ITERATIONS
    ).hex()


settings = get_settings()
USERS = {
    "viewer": UserRecord(
        _hash(settings.viewer_password.get_secret_value(), "viewer"),
        User(username="viewer", role=Role.VIEWER),
    ),
    "analyst": UserRecord(
        _hash(settings.analyst_password.get_secret_value(), "analyst"),
        User(username="analyst", role=Role.ANALYST, departments=["payments", "platform"]),
    ),
    "admin": UserRecord(
        _hash(settings.admin_password.get_secret_value(), "admin"),
        User(
            username="admin",
            role=Role.ADMIN,
            departments=["payments", "platform", "security"],
            access_levels=["public", "internal", "confidential"],
        ),
    ),
}


async def current_user(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> User:
    """Authenticate one request and return the trusted user/role security principal."""

    record = USERS.get(credentials.username)
    # Always derive and compare a hash so unknown usernames do not create an obvious timing oracle.
    # Unknown users still perform the same expensive derivation to reduce username timing leaks.
    expected = record.password_hash if record else "0" * 64
    supplied = _hash(credentials.password, credentials.username)
    valid = record is not None and secrets.compare_digest(expected, supplied)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return record.user
