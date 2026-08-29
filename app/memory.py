import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass

from app.config import get_settings


@dataclass
class Turn:
    question: str
    answer: str


class SessionMemory:
    """Bounded, concurrency-safe POC memory. Replace with Redis in production."""

    def __init__(self) -> None:
        self._sessions: dict[str, deque[Turn]] = defaultdict(
            lambda: deque(maxlen=get_settings().memory_max_turns)
        )
        self._lock = asyncio.Lock()

    async def context(self, session_id: str, limit: int = 4) -> list[Turn]:
        async with self._lock:
            return list(self._sessions[session_id])[-limit:]

    async def add(self, session_id: str, question: str, answer: str) -> None:
        async with self._lock:
            self._sessions[session_id].append(Turn(question, answer))

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)


memory = SessionMemory()
