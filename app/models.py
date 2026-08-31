"""Pydantic contracts exchanged between API clients, agents, tools, and persistence."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings


class Role(StrEnum):
    """Supported authorization roles ordered conceptually from least to most privileged."""

    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"


class User(BaseModel):
    """Authenticated user context propagated through the graph and every tool call."""

    username: str
    role: Role
    departments: list[str] = Field(default_factory=list)
    access_levels: list[str] = Field(default_factory=lambda: ["public", "internal"])


class ChatRequest(BaseModel):
    """Validated request for one conversational turn."""

    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1, max_length=100, pattern=r"^[\w-]+$")
    filters: dict[str, str] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        """Normalize whitespace and enforce the configurable prompt-size limit."""

        value = value.strip()
        if len(value) > get_settings().max_query_length:
            raise ValueError("message is too long")
        return value

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, value: dict[str, str]) -> dict[str, str]:
        """Allow only indexed metadata fields and bounded scalar filter values."""

        allowed = {"department", "document_type", "created_date"}
        if unknown := value.keys() - allowed:
            raise ValueError(f"unsupported filters: {', '.join(sorted(unknown))}")
        if any(not item or len(item) > 100 for item in value.values()):
            raise ValueError("filter values must contain 1-100 characters")
        return value


class Evidence(BaseModel):
    """Authorized, scored document evidence returned by hybrid retrieval."""

    document_id: str
    title: str
    text: str
    score: float = Field(ge=0, le=1)
    metadata: dict[str, Any]


class ActivityEvent(BaseModel):
    """Observable lifecycle event streamed to the agent activity panel."""

    type: Literal["state", "tool", "retrieval", "memory", "validation", "token", "final", "error"]
    node: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Non-streaming chat response including provenance and execution activity."""

    answer: str
    session_id: str
    citations: list[Evidence]
    trace_id: str
    activities: list[ActivityEvent]


class FeedbackRequest(BaseModel):
    """User quality signal attached to a conversation the user owns."""

    session_id: str = Field(min_length=1, max_length=100, pattern=r"^[\w-]+$")
    rating: Literal[-1, 1]
    comment: str = Field(default="", max_length=1000)
