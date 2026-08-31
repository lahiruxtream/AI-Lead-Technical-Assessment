"""Grounded generation tests covering the credential-free streaming fallback."""

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


@pytest.mark.asyncio
async def test_procedure_answer_uses_best_runbook_without_distractor_documents():
    evidence = [
        Evidence(
            document_id="RUN-1",
            title="Recovery Runbook",
            text="Acknowledge the alert. Enable the circuit breaker. Verify recovery.",
            score=0.9,
            metadata={"document_type": "runbook"},
        ),
        Evidence(
            document_id="PROD-1",
            title="Product Specification",
            text="The product is available twenty-four hours per day.",
            score=0.8,
            metadata={"document_type": "product"},
        ),
    ]

    answer = await generate_answer("What is the recovery procedure?", evidence, "", "")

    assert "circuit breaker" in answer
    assert "[RUN-1]" in answer
    assert "PROD-1" not in answer
