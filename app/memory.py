"""Persistent, user-isolated conversation and answer-quality feedback storage."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from app.config import get_settings


@dataclass
class Turn:
    """Minimal historical turn supplied to the model's bounded context window."""

    question: str
    answer: str


class SessionMemory:
    """Persistent, user-isolated conversation memory backed by SQLite."""

    def __init__(self) -> None:
        self.db_path = Path(get_settings().memory_db_path)

    async def initialize(self) -> None:
        """Create idempotent SQLite schema and lookup indexes at application startup."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES conversations(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(username, updated_at);
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
                    comment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES conversations(session_id)
                );
                """
            )
            await db.commit()

    async def context(self, session_id: str, username: str, limit: int = 4) -> list[Turn]:
        """Return the latest owned turns in chronological order for prompt context."""

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT t.question, t.answer FROM turns t
                   JOIN conversations c ON c.session_id = t.session_id
                   WHERE t.session_id = ? AND c.username = ?
                   ORDER BY t.id DESC LIMIT ?""",
                (session_id, username, limit),
            )
            rows = await cursor.fetchall()
        return [Turn(question=row[0], answer=row[1]) for row in reversed(rows)]

    async def add(
        self, session_id: str, username: str, question: str, answer: str, citations_json: str = "[]"
    ) -> None:
        """Persist a turn after atomically verifying conversation ownership."""

        now = datetime.now(UTC).isoformat()
        title = question.strip().replace("\n", " ")[:60] or "New conversation"
        async with aiosqlite.connect(self.db_path) as db:
            # Upsert updates only when the existing row belongs to the same authenticated user.
            await db.execute(
                """INSERT INTO conversations(session_id, username, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                   WHERE conversations.username = excluded.username""",
                (session_id, username, title, now, now),
            )
            cursor = await db.execute(
                "SELECT username FROM conversations WHERE session_id = ?", (session_id,)
            )
            # Verify ownership again before inserting a turn to handle session-ID collisions safely.
            owner = await cursor.fetchone()
            if not owner or owner[0] != username:
                raise PermissionError("Conversation belongs to another user")
            await db.execute(
                """INSERT INTO turns(session_id, question, answer, citations_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, question, answer, citations_json, now),
            )
            await db.commit()

    async def list_sessions(self, username: str, limit: int = 50) -> list[dict[str, str]]:
        """List only conversations owned by the authenticated user."""

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT session_id, title, created_at, updated_at FROM conversations
                   WHERE username = ? ORDER BY updated_at DESC LIMIT ?""",
                (username, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def messages(self, session_id: str, username: str) -> list[dict[str, object]]:
        """Restore an owned conversation as UI-compatible chat messages."""

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT t.question, t.answer, t.citations_json FROM turns t
                   JOIN conversations c ON c.session_id = t.session_id
                   WHERE t.session_id = ? AND c.username = ? ORDER BY t.id""",
                (session_id, username),
            )
            rows = await cursor.fetchall()
        import json

        messages: list[dict[str, object]] = []
        for question, answer, citations_json in rows:
            messages.extend(
                [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer, "citations": json.loads(citations_json)},
                ]
            )
        return messages

    async def add_feedback(
        self, session_id: str, username: str, rating: int, comment: str = ""
    ) -> None:
        """Persist quality feedback only when the user owns the conversation."""
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            # Returning one generic not-found result avoids revealing another user's session IDs.
            cursor = await db.execute(
                "SELECT 1 FROM conversations WHERE session_id = ? AND username = ?",
                (session_id, username),
            )
            if not await cursor.fetchone():
                raise LookupError("Conversation not found")
            await db.execute(
                "INSERT INTO feedback(session_id, username, rating, comment, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, username, rating, comment, now),
            )
            await db.commit()


memory = SessionMemory()
