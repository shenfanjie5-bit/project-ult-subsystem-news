from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from typing import Sequence

import pytest

from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference, SourceReferenceLocator
from subsystem_news.errors import ContractViolationError
from subsystem_news.runtime.models import CandidatePayload
from subsystem_news.runtime.submit import (
    DefaultSubsystemSdkClient,
    SubmitReceipt,
    submit_candidates,
    validate_candidate_batch,
)


def source_reference() -> SourceReference:
    return SourceReference(
        source_id="runtime-source",
        url="https://runtime.example.com/articles/1",
        provider_key="runtime-1",
        original_locator=SourceReferenceLocator(
            locator_type="fixture",
            locator_value="runtime-1",
        ),
    )


def entity() -> InvolvedEntity:
    return InvolvedEntity(
        mention_text="Acme Corp",
        canonical_id="entity:acme",
        resolution_status="resolved",
        type_hint="company",
    )


def evidence() -> EvidenceSpan:
    return EvidenceSpan(
        article_id="article-1",
        start_char=0,
        end_char=9,
        quote="Acme Corp",
        locator="body",
    )


def fact_candidate() -> NewsFactCandidate:
    return NewsFactCandidate(
        candidate_id="fact-1",
        article_id="article-1",
        cluster_id="cluster-1",
        source_reference=source_reference(),
        fact_type="contract",
        summary="Acme signed a supply contract.",
        involved_entities=[entity()],
        event_time=datetime(2026, 2, 1, tzinfo=timezone.utc),
        evidence_spans=[evidence()],
        confidence=0.9,
        source_reliability_tier="A",
    )


def signal_candidate() -> NewsSignalCandidate:
    return NewsSignalCandidate(
        candidate_id="signal-1",
        article_id="article-1",
        cluster_id="cluster-1",
        source_reference=source_reference(),
        signal_type="event_impact",
        direction="positive",
        magnitude="medium",
        affected_entities=[entity()],
        impact_scope="company",
        time_horizon="short",
        rationale="The contract adds revenue visibility.",
        evidence_spans=[evidence()],
        confidence=0.86,
    )


def graph_candidate() -> NewsGraphDeltaCandidate:
    return NewsGraphDeltaCandidate(
        candidate_id="graph-1",
        article_id="article-1",
        source_reference=source_reference(),
        subject_entity=entity(),
        relation_type="acquired",
        object_entity=InvolvedEntity(
            mention_text="Globex Inc",
            canonical_id="entity:globex",
            resolution_status="resolved",
            type_hint="company",
        ),
        delta_action="add",
        valid_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
        evidence_spans=[evidence()],
        confidence=0.88,
        requires_manual_review=True,
    )


class RetrySdkClient:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls: list[list[CandidatePayload]] = []

    def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
        self.calls.append(list(batch))
        if len(self.calls) <= self.failures:
            raise RuntimeError("transient submit failure")
        return SubmitReceipt(
            accepted_count=len(batch),
            submitted_candidate_ids=[candidate.candidate_id for candidate in batch],
        )


def test_validate_candidate_batch_accepts_fact_and_signal_candidates() -> None:
    batch = validate_candidate_batch(
        [fact_candidate(), signal_candidate(), graph_candidate()]
    )

    assert [candidate.export_contract for candidate in batch] == ["Ex-1", "Ex-2", "Ex-3"]


def test_validate_candidate_batch_rejects_missing_source_reference_and_evidence() -> None:
    missing_source = NewsFactCandidate.model_construct(
        candidate_id="fact-bad",
        article_id="article-1",
        cluster_id="cluster-1",
        evidence_spans=[evidence()],
        export_contract="Ex-1",
    )
    missing_evidence = NewsFactCandidate.model_construct(
        candidate_id="fact-bad",
        article_id="article-1",
        cluster_id="cluster-1",
        source_reference=source_reference(),
        evidence_spans=[],
        export_contract="Ex-1",
    )

    with pytest.raises(ContractViolationError, match="source_reference"):
        validate_candidate_batch([missing_source])
    with pytest.raises(ContractViolationError, match="evidence_spans"):
        validate_candidate_batch([missing_evidence])


def test_validate_candidate_batch_rejects_incomplete_ex2_fields() -> None:
    missing_direction = NewsSignalCandidate.model_construct(
        candidate_id="signal-bad",
        article_id="article-1",
        cluster_id="cluster-1",
        source_reference=source_reference(),
        evidence_spans=[evidence()],
        export_contract="Ex-2",
        magnitude="medium",
        affected_entities=[entity()],
    )

    with pytest.raises(ContractViolationError, match="direction"):
        validate_candidate_batch([missing_direction])


def test_validate_candidate_batch_rejects_unresolved_ex3_endpoint() -> None:
    unresolved = InvolvedEntity(
        mention_text="Globex Inc",
        canonical_id=None,
        resolution_status="unresolved",
        type_hint="company",
    )
    candidate = graph_candidate().model_copy(update={"object_entity": unresolved})

    with pytest.raises(ContractViolationError, match="object_entity"):
        validate_candidate_batch([candidate])


def test_validate_candidate_batch_rejects_ex3_without_manual_review() -> None:
    candidate = graph_candidate().model_copy(update={"requires_manual_review": False})

    with pytest.raises(ContractViolationError, match="requires_manual_review"):
        validate_candidate_batch([candidate])


def test_submit_candidates_retries_transient_failures() -> None:
    client = RetrySdkClient(failures=1)

    receipt = submit_candidates([fact_candidate()], client, max_retries=2)

    assert receipt.accepted_count == 1
    assert len(client.calls) == 2


def test_submit_candidates_raises_after_final_retry_failure() -> None:
    client = RetrySdkClient(failures=3)

    with pytest.raises(RuntimeError, match="transient"):
        submit_candidates([fact_candidate()], client, max_retries=1)

    assert len(client.calls) == 2


def test_default_sdk_client_rejects_missing_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage 2.9 canonical-mapper rewrite: SDK ``submit(payload)`` is now
    invoked per-candidate via ``subsystem_sdk.submit.submit``, which
    delegates to the runtime singleton's ``submit``. Returning ``None``
    from the SDK leaves accepted/rejected ambiguous, so the news
    adapter raises rather than silently treating the candidate as
    accepted or rejected.

    Patch the runtime-resolved submit function (NOT sys.modules — the
    submodule import path bypasses top-level monkeypatching).
    """

    import subsystem_sdk.submit as sdk_submit_pkg

    # Patch the binding news's `from subsystem_sdk.submit import submit
    # as sdk_submit` actually resolves to (the package-level re-export,
    # not the source `client.submit`).
    monkeypatch.setattr(sdk_submit_pkg, "submit", lambda _payload: None)

    with pytest.raises(ContractViolationError, match="returned no receipt"):
        DefaultSubsystemSdkClient().submit([fact_candidate()])


def test_default_sdk_client_rejects_unsupported_receipt_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage 2.9 canonical-mapper rewrite: SDK now returns SDK-shape
    ``SubmitReceipt`` objects with an ``.accepted`` attribute, NOT the
    old news-shape dicts (``accepted_count`` / ``submitted_candidate_ids``).
    A return value missing ``.accepted`` is unsupported — the news
    adapter raises instead of silently mis-classifying the candidate.
    """

    import subsystem_sdk.submit as sdk_submit_pkg

    monkeypatch.setattr(
        sdk_submit_pkg,
        "submit",
        lambda _payload: {
            "accepted_count": 1,
            "submitted_candidate_ids": [],
        },
    )

    with pytest.raises(ContractViolationError, match="unsupported receipt"):
        DefaultSubsystemSdkClient().submit([fact_candidate()])


def test_submit_candidates_requires_direct_client_receipt_partition() -> None:
    class BadReceiptClient:
        def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
            del batch
            return SubmitReceipt(accepted_count=0, rejected_count=0)

    with pytest.raises(ContractViolationError, match="counts must equal submitted batch"):
        submit_candidates([fact_candidate()], BadReceiptClient())
