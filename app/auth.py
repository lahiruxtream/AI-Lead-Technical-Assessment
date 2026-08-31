import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.models import Role, User

security = HTTPBasic()


@dataclass(frozen=True)
class UserRecord:
    password_hash: str
    user: User


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


USERS = {
    "viewer": UserRecord(_hash("viewer123"), User(username="viewer", role=Role.VIEWER)),
    "analyst": UserRecord(
        _hash("analyst123"),
        User(username="analyst", role=Role.ANALYST, departments=["payments", "platform"]),
    ),
    "admin": UserRecord(
        _hash("admin123"),
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
    record = USERS.get(credentials.username)
    valid = record and secrets.compare_digest(record.password_hash, _hash(credentials.password))
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return record.user
