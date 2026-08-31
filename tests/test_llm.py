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


@pytest.mark.asyncio
async def test_architecture_question_returns_components_from_architecture_document():
    evidence = [
        Evidence(
            document_id="ARCH-1",
            title="Architecture",
            text="The platform uses an API gateway. Services publish through Kafka.",
            score=0.9,
            metadata={"document_type": "architecture"},
        ),
        Evidence(
            document_id="INC-1",
            title="Incident",
            text="The API failed for ten minutes.",
            score=0.8,
            metadata={"document_type": "incident"},
        ),
    ]

    answer = await generate_answer("Explain the platform architecture.", evidence, "", "")

    assert "API gateway" in answer
    assert "Kafka" in answer
    assert "[ARCH-1]" in answer
    assert "[INC-1]" not in answer


@pytest.mark.asyncio
async def test_follow_up_prefers_previously_cited_incident_and_returns_recovery_action():
    evidence = [
        Evidence(
            document_id="INC-2",
            title="Another incident",
            text="A different outage occurred. Remediation introduced a cache.",
            score=0.9,
            metadata={"document_type": "incident"},
        ),
        Evidence(
            document_id="INC-1",
            title="Previous incident",
            text="The payment API failed. Resolution included bounded retries.",
            score=0.7,
            metadata={"document_type": "incident"},
        ),
    ]

    answer = await generate_answer(
        "What recovery actions were taken for that incident?",
        evidence,
        "Assistant: The payment API failed. [INC-1]",
        "",
    )

    assert "bounded retries" in answer
    assert "[INC-1]" in answer
    assert "[INC-2]" not in answer


@pytest.mark.asyncio
async def test_mcp_result_is_rendered_without_internal_serialization():
    answer = await generate_answer(
        "Who owns the payments API and what is its support channel?",
        [
            Evidence(
                document_id="DOC-1",
                title="Document",
                text="Unrelated document.",
                score=0.1,
                metadata={},
            )
        ],
        "",
        'MCP_RESULT:{"payments-api":{"owner":"Payments Platform","tier":1,"channel":"#pay-ops"}}',
    )

    assert "Payments Platform" in answer
    assert "#pay-ops" in answer
    assert "MCP_RESULT" not in answer
