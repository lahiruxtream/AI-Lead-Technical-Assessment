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


@pytest.mark.asyncio
async def test_incident_summary_identifies_recurring_causes_without_raw_analysis():
    evidence = [
        Evidence(
            document_id="INC-PAY-2025-001",
            title="January outage",
            text=(
                "Payment authorization failed for 31 minutes. "
                "Root cause: database connection pool exhaustion. The retry storm amplified load."
            ),
            score=0.9,
            metadata={"document_type": "incident", "created_date": "2025-01-15"},
        ),
        Evidence(
            document_id="INC-PAY-2025-002",
            title="June outage",
            text=(
                "Gateway latency caused failures for 46 minutes. "
                "Root cause: connection pool exhaustion caused by unbounded retries."
            ),
            score=0.8,
            metadata={"document_type": "incident", "created_date": "2025-06-09"},
        ),
    ]

    answer = await generate_answer(
        "Summarize all payment outages in 2025 and identify recurring root causes.",
        evidence,
        "",
        "Batch 1: internal diagnostic. Structured metrics: internal diagnostic.",
    )

    assert "Recurring root causes:" in answer
    assert "connection-pool exhaustion appeared in 2 of 2 incidents" in answer
    assert "Batch 1" not in answer
    assert "Structured metrics" not in answer
