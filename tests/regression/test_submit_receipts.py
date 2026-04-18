from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import pytest

from subsystem_news.contracts.candidates import InvolvedEntity, NewsFactCandidate
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference, SourceReferenceLocator
from subsystem_news.errors import ContractViolationError
from subsystem_news.runtime.models import CandidatePayload
from subsystem_news.runtime.submit import SubmitReceipt, submit_candidates


class ReceiptClient:
    def __init__(self, receipt: SubmitReceipt) -> None:
        self.receipt = receipt

    def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
        del batch
        return self.receipt


def test_submit_receipt_accepts_partial_accept_and_full_reject_partitions() -> None:
    first = _candidate("fact-a")
    second = _candidate("fact-b")

    partial = submit_candidates(
        [first, second],
        ReceiptClient(
            SubmitReceipt(
                accepted_count=1,
                rejected_count=1,
                submitted_candidate_ids=["fact-a"],
                rejected_candidate_ids=["fact-b"],
            )
        ),
    )
    full_reject = submit_candidates(
        [first, second],
        ReceiptClient(
            SubmitReceipt(
                accepted_count=0,
                rejected_count=2,
                rejected_candidate_ids=["fact-a", "fact-b"],
            )
        ),
    )

    assert partial.accepted_count == 1
    assert partial.rejected_count == 1
    assert full_reject.accepted_count == 0
    assert full_reject.rejected_count == 2


@pytest.mark.parametrize(
    ("receipt", "message"),
    [
        (
            SubmitReceipt(
                accepted_count=1,
                rejected_count=1,
                submitted_candidate_ids=["unknown"],
                rejected_candidate_ids=["fact-b"],
            ),
            "unknown candidate_id",
        ),
        (
            SubmitReceipt(
                accepted_count=2,
                submitted_candidate_ids=["fact-a", "fact-a"],
            ),
            "must not contain duplicates",
        ),
        (
            SubmitReceipt(
                accepted_count=1,
                rejected_count=1,
                submitted_candidate_ids=["fact-a"],
            ),
            "rejected_candidate_ids",
        ),
        (
            SubmitReceipt(
                accepted_count=1,
                rejected_count=0,
                submitted_candidate_ids=[],
            ),
            "counts must equal submitted batch",
        ),
    ],
)
def test_submit_receipt_rejects_ambiguous_partitions(
    receipt: SubmitReceipt,
    message: str,
) -> None:
    with pytest.raises(ContractViolationError, match=message):
        submit_candidates([_candidate("fact-a"), _candidate("fact-b")], ReceiptClient(receipt))


def _source_reference() -> SourceReference:
    return SourceReference(
        source_id="submit-regression",
        url="https://submit.example.com/article",
        provider_key="submit-regression",
        original_locator=SourceReferenceLocator(
            locator_type="fixture",
            locator_value="submit-regression",
        ),
    )


def _candidate(candidate_id: str) -> NewsFactCandidate:
    return NewsFactCandidate(
        candidate_id=candidate_id,
        article_id=f"article-{candidate_id}",
        cluster_id="cluster-submit",
        source_reference=_source_reference(),
        fact_type="contract",
        summary="Acme Corp signed a contract.",
        involved_entities=[
            InvolvedEntity(
                mention_text="Acme Corp",
                canonical_id="entity:acme-corp",
                resolution_status="resolved",
                type_hint="company",
            )
        ],
        event_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
        evidence_spans=[
            EvidenceSpan(
                article_id=f"article-{candidate_id}",
                start_char=0,
                end_char=9,
                quote="Acme Corp",
                locator="body",
            )
        ],
        confidence=0.9,
        source_reliability_tier="A",
    )
