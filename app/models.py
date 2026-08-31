from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"


class User(BaseModel):
    username: str
    role: Role
    departments: list[str] = Field(default_factory=list)
    access_levels: list[str] = Field(default_factory=lambda: ["public", "internal"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1, max_length=100, pattern=r"^[\w-]+$")
    filters: dict[str, str] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if len(value) > get_settings().max_query_length:
            raise ValueError("message is too long")
        return value


class Evidence(BaseModel):
    document_id: str
    title: str
    text: str
    score: float = Field(ge=0, le=1)
    metadata: dict[str, Any]


class ActivityEvent(BaseModel):
    type: Literal["state", "tool", "retrieval", "memory", "validation", "token", "final", "error"]
    node: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    citations: list[Evidence]
    trace_id: str
    activities: list[ActivityEvent]


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100, pattern=r"^[\w-]+$")
    rating: Literal[-1, 1]
    comment: str = Field(default="", max_length=1000)
