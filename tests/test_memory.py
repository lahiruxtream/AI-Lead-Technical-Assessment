import pytest

from app.memory import SessionMemory


@pytest.mark.asyncio
async def test_conversations_persist_and_are_user_isolated(tmp_path):
    store = SessionMemory()
    store.db_path = tmp_path / "conversations.db"
    await store.initialize()
    await store.add("session-1", "viewer", "First question", "First answer")

    sessions = await store.list_sessions("viewer")
    assert sessions[0]["session_id"] == "session-1"
    assert await store.messages("session-1", "other-user") == []

    restored = await store.messages("session-1", "viewer")
    assert restored == [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer", "citations": []},
    ]

    await store.add_feedback("session-1", "viewer", 1, "Grounded and useful")
    with pytest.raises(LookupError):
        await store.add_feedback("session-1", "other-user", -1)
