import pytest

from app.llm import generate_answer
from app.models import Evidence


@pytest.mark.asyncio
async def test_local_answer_streams_tokens_and_matches_final_answer():
    chunks: list[str] = []

    async def sink(chunk: str) -> None:
        chunks.append(chunk)

    evidence = [
        Evidence(
            document_id="DOC-1",
            title="Runbook",
            text="Restart the payment worker. Then verify the queue.",
            score=1,
            metadata={"access_level": "internal"},
        )
    ]
    answer = await generate_answer("How do I recover?", evidence, "", "", sink)
    assert chunks
    assert "".join(chunks) == answer
    assert "[DOC-1]" in answer
