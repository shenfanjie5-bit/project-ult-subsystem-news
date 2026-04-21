"""Cross-repo alignment: subsystem-news candidate models ↔
contracts.schemas Ex payload models.

CLAUDE.md (news + contracts both): Ex schemas are defined ONLY in
``contracts``; news's local Ex-1/Ex-2/Ex-3 candidate models must
produce wire payloads that contracts accepts after the canonical
mapper (``runtime.submit._normalize_for_sdk``) runs.

Module-level skip on missing dep — install [contracts-schemas] extra
to run this lane:

    pip install -e ".[dev,contracts-schemas]"
    pytest tests/contract/test_contracts_alignment.py

Two layers of cross-repo verification (sibling of subsystem-announcement
follow-up #3):

**Layer 1 (PRODUCTION FIX VERIFIED):** the production canonical mapper
``runtime/submit.py:_normalize_for_sdk`` produces wire payloads with
SDK-required fields (``subsystem_id`` + ``produced_at``) and contracts
canonical structure (rename ``candidate_id``→``fact_id``/``signal_id``/
``delta_id``, ``InvolvedEntity``→canonical ``entity_id`` strings, news
``Direction``→contracts ``Direction``, evidence_spans→canonical evidence
ref strings, etc.). Tests in this file invoke the REAL production
helpers (``runtime.submit._validated_payload``) — NOT a test-side
workaround. These assertions are unconditional: any drift between news's
production output and the SDK-required field set is a P1.

**Layer 2 (REAL ROUND-TRIP through contracts v0.1.3 canonical schema):**
the production wire shape ROUND TRIPS through real
``contracts.Ex1/2/3.model_validate()`` end-to-end after
``_strip_sdk_envelope`` removes the SDK routing fields. Any drift in
either the news mapper or the contracts canonical wire shape fails this
lane loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

contracts_schemas = pytest.importorskip(
    "contracts.schemas",
    reason=(
        "contracts package not installed; install [contracts-schemas] "
        "extra to run cross-repo alignment tests"
    ),
)


# ── Helpers — minimal valid candidates for each Ex type ─────────────


def _build_ex1_candidate():
    from subsystem_news.contracts.candidates import (
        InvolvedEntity,
        NewsFactCandidate,
    )
    from subsystem_news.contracts.evidence import EvidenceSpan
    from subsystem_news.contracts.source_reference import (
        SourceReference,
        SourceReferenceLocator,
    )

    return NewsFactCandidate(
        candidate_id="align-news-ex1-001",
        article_id="align-news-art-001",
        cluster_id="align-news-cluster-001",
        source_reference=SourceReference(
            source_id="align-source-A1",
            url="https://example-approved-news.com/a/1",
            provider_key=None,
            original_locator=SourceReferenceLocator(
                locator_type="rss_guid",
                locator_value="align-locator-001",
            ),
        ),
        fact_type="contract",
        summary="placeholder align summary",
        involved_entities=[
            InvolvedEntity(
                mention_text="Align Corp",
                canonical_id="ENT_STOCK_ALIGN_001",
                resolution_status="resolved",
                type_hint="company",
            ),
        ],
        event_time=datetime(2026, 1, 1, tzinfo=UTC),
        confidence=0.91,
        source_reliability_tier="A",
        evidence_spans=[
            __import__(
                "subsystem_news.contracts.evidence", fromlist=["EvidenceSpan"]
            ).EvidenceSpan(
                article_id="align-news-art-001",
                start_char=0,
                end_char=11,
                quote="placeholder",
                locator="title",
            ),
        ],
    )


def _build_ex2_candidate():
    from subsystem_news.contracts.candidates import (
        InvolvedEntity,
        NewsSignalCandidate,
    )
    from subsystem_news.contracts.evidence import EvidenceSpan
    from subsystem_news.contracts.source_reference import (
        SourceReference,
        SourceReferenceLocator,
    )

    return NewsSignalCandidate(
        candidate_id="align-news-ex2-001",
        article_id="align-news-art-001",
        cluster_id="align-news-cluster-001",
        source_reference=SourceReference(
            source_id="align-source-A1",
            url="https://example-approved-news.com/a/1",
            provider_key=None,
            original_locator=SourceReferenceLocator(
                locator_type="rss_guid",
                locator_value="align-locator-001",
            ),
        ),
        signal_type="event_impact",
        direction="positive",
        magnitude=0.7,
        affected_entities=[
            InvolvedEntity(
                mention_text="Align Corp",
                canonical_id="ENT_STOCK_ALIGN_001",
                resolution_status="resolved",
                type_hint="company",
            ),
        ],
        impact_scope="company",
        time_horizon="short",
        rationale="placeholder rationale",
        confidence=0.85,
        evidence_spans=[
            EvidenceSpan(
                article_id="align-news-art-001",
                start_char=0,
                end_char=11,
                quote="placeholder",
                locator="body",
            ),
        ],
    )


def _build_ex3_candidate():
    from subsystem_news.contracts.candidates import (
        InvolvedEntity,
        NewsGraphDeltaCandidate,
    )
    from subsystem_news.contracts.evidence import EvidenceSpan
    from subsystem_news.contracts.source_reference import (
        SourceReference,
        SourceReferenceLocator,
    )

    return NewsGraphDeltaCandidate(
        candidate_id="align-news-ex3-001",
        article_id="align-news-art-001",
        source_reference=SourceReference(
            source_id="align-source-A1",
            url="https://example-approved-news.com/a/1",
            provider_key=None,
            original_locator=SourceReferenceLocator(
                locator_type="rss_guid",
                locator_value="align-locator-001",
            ),
        ),
        subject_entity=InvolvedEntity(
            mention_text="Align Corp",
            canonical_id="ENT_STOCK_ALIGN_001",
            resolution_status="resolved",
            type_hint="company",
        ),
        relation_type="supplier_of",
        object_entity=InvolvedEntity(
            mention_text="Counterparty Inc",
            canonical_id="ENT_STOCK_COUNTERPARTY_001",
            resolution_status="resolved",
            type_hint="company",
        ),
        delta_action="add",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        confidence=0.93,
        requires_manual_review=True,
        evidence_spans=[
            EvidenceSpan(
                article_id="align-news-art-001",
                start_char=0,
                end_char=11,
                quote="placeholder",
                locator="title",
            ),
            EvidenceSpan(
                article_id="align-news-art-001",
                start_char=20,
                end_char=35,
                quote="dual_evidence!!",
                locator="body",
            ),
        ],
    )


# ── Layer 1: production normalizer adds SDK-required fields ─────────


class TestProductionNormalizerAddsSdkRequiredFields:
    """Layer 1 (unconditional): production ``_validated_payload`` adds
    ``subsystem_id`` + ``produced_at`` (the SDK envelope routing field
    that ``assert_producer_only`` requires) for each Ex type. Drift
    between production output and the SDK-required field set is a P1.
    """

    def test_ex1_production_payload_includes_subsystem_id_and_produced_at(
        self,
    ) -> None:
        from subsystem_news.runtime.submit import _validated_payload

        wire = _validated_payload(_build_ex1_candidate())

        assert wire["subsystem_id"] == "subsystem-news"
        assert "produced_at" in wire
        # Ex-1 stamps extracted_at = produced_at = current UTC at submit
        # time (news has no candidate-side production timestamp).
        assert wire["extracted_at"] == wire["produced_at"]

    def test_ex2_production_payload_includes_subsystem_id_and_produced_at(
        self,
    ) -> None:
        from subsystem_news.runtime.submit import _validated_payload

        wire = _validated_payload(_build_ex2_candidate())

        assert wire["subsystem_id"] == "subsystem-news"
        assert "produced_at" in wire
        # No top-level generated_at (news has no such field; produced_at
        # is the canonical timestamp).
        assert "generated_at" not in wire

    def test_ex3_production_payload_includes_subsystem_id_and_produced_at(
        self,
    ) -> None:
        from subsystem_news.runtime.submit import _validated_payload

        wire = _validated_payload(_build_ex3_candidate())

        assert wire["subsystem_id"] == "subsystem-news"
        assert "produced_at" in wire
        assert "generated_at" not in wire


class TestForbiddenIngestMetadataKept:
    """Iron rule: news must never emit ``submitted_at`` / ``ingest_seq`` /
    ``layer_b_receipt_id`` (Layer B-owned) on the wire payload —
    contracts.semantics.assert_no_ingest_metadata enforces this.
    """

    def test_no_ingest_metadata_in_canonical_wire(self) -> None:
        from subsystem_news.runtime.submit import _validated_payload

        forbidden = {"submitted_at", "ingest_seq", "layer_b_receipt_id"}
        for build in (
            _build_ex1_candidate,
            _build_ex2_candidate,
            _build_ex3_candidate,
        ):
            wire = _validated_payload(build())
            leaked = forbidden.intersection(wire)
            assert not leaked, (
                f"news canonical mapper leaked Layer-B-only ingest "
                f"metadata: {sorted(leaked)}"
            )


# ── Layer 2: REAL ROUND-TRIP through contracts canonical schema ─────


class TestProductionWirePayloadPassesRealContractsValidation:
    """Layer 2: the production wire payload ROUND TRIPS through real
    ``contracts.schemas.Ex1/2/3.model_validate()`` end-to-end after
    SDK ``_strip_sdk_envelope`` removes ``ex_type`` / ``semantic`` /
    ``produced_at``. Any regression in either the news mapper or the
    contracts canonical wire shape fails this lane loudly.
    """

    def test_ex1_wire_round_trip_through_real_contracts(self) -> None:
        from contracts.schemas import Ex1CandidateFact

        from subsystem_news.runtime.submit import _validated_payload
        from subsystem_sdk.validate.engine import strip_sdk_envelope

        candidate = _build_ex1_candidate()
        wire = _validated_payload(candidate)
        stripped = dict(strip_sdk_envelope(wire))
        model = Ex1CandidateFact.model_validate(stripped)

        assert model.subsystem_id == "subsystem-news"
        assert model.entity_id == "ENT_STOCK_ALIGN_001"  # InvolvedEntity[0]
        assert model.fact_id == candidate.candidate_id
        assert model.fact_type == candidate.fact_type
        # Ex-1 source_reference MUST stay at top-level (contracts.Ex1
        # REQUIRED).
        assert model.source_reference["source_id"] == candidate.source_reference.source_id
        # Canonical evidence refs are deterministic from article_id +
        # locator + start_char + end_char.
        assert model.evidence == [
            f"{span.article_id}#{span.locator}:{span.start_char}-{span.end_char}"
            for span in candidate.evidence_spans
        ]
        # producer_context holds the news-local provenance.
        assert model.producer_context is not None
        assert model.producer_context["article_id"] == candidate.article_id
        assert model.producer_context["cluster_id"] == candidate.cluster_id
        assert "involved_entities" in model.producer_context
        assert "evidence_spans_detail" in model.producer_context

    def test_ex2_wire_round_trip_through_real_contracts(self) -> None:
        from contracts.schemas import Ex2CandidateSignal

        from subsystem_news.runtime.submit import _validated_payload
        from subsystem_sdk.validate.engine import strip_sdk_envelope

        candidate = _build_ex2_candidate()
        wire = _validated_payload(candidate)
        stripped = dict(strip_sdk_envelope(wire))
        model = Ex2CandidateSignal.model_validate(stripped)

        assert model.subsystem_id == "subsystem-news"
        assert model.signal_id == candidate.candidate_id
        # news Direction "positive" → contracts Direction.bullish (enum
        # mapping in _NEWS_DIRECTION_TO_CONTRACTS_DIRECTION).
        assert model.direction.value == "bullish"
        # contracts v0.1.3 allows empty affected_sectors; news has no
        # sector data so it emits []. graph-engine downstream is
        # responsible for sector enrichment.
        assert model.affected_sectors == []
        # affected_entities now strings (canonical_id), not full
        # InvolvedEntity objects.
        assert model.affected_entities == ["ENT_STOCK_ALIGN_001"]
        assert model.time_horizon == candidate.time_horizon
        # Canonical evidence refs derived from evidence_spans.
        assert model.evidence == [
            f"{span.article_id}#{span.locator}:{span.start_char}-{span.end_char}"
            for span in candidate.evidence_spans
        ]
        # Ex-2 source_reference goes into producer_context (Ex-2
        # contracts has no canonical slot for it).
        assert model.producer_context is not None
        assert model.producer_context["source_reference"]["source_id"] == (
            candidate.source_reference.source_id
        )
        # Full InvolvedEntity preserved in producer_context.
        assert "affected_entities" in model.producer_context

        # No top-level generated_at (renamed/dropped); SDK doesn't strip
        # generated_at and contracts.Ex2 would reject it as extra.
        assert "generated_at" not in wire

    def test_ex3_wire_round_trip_through_real_contracts(self) -> None:
        from contracts.schemas import Ex3CandidateGraphDelta

        from subsystem_news.runtime.submit import _validated_payload
        from subsystem_sdk.validate.engine import strip_sdk_envelope

        candidate = _build_ex3_candidate()
        wire = _validated_payload(candidate)
        stripped = dict(strip_sdk_envelope(wire))
        model = Ex3CandidateGraphDelta.model_validate(stripped)

        assert model.subsystem_id == "subsystem-news"
        assert model.delta_id == candidate.candidate_id
        # delta_type passes through as DeltaAction string ("add").
        assert model.delta_type == "add"
        assert model.relation_type == "supplier_of"
        # source_node / target_node = canonical_id strings.
        assert model.source_node == "ENT_STOCK_ALIGN_001"
        assert model.target_node == "ENT_STOCK_COUNTERPARTY_001"
        # Two evidence refs serialized from news's two EvidenceSpans.
        assert len(model.evidence) == 2
        # Ex-3 source_reference + news-local confidence + subject/object
        # InvolvedEntity all in producer_context.
        assert model.producer_context is not None
        assert model.producer_context["source_reference"]["source_id"] == (
            candidate.source_reference.source_id
        )
        assert model.producer_context["confidence"] == candidate.confidence
        assert "subject_entity" in model.producer_context
        assert "object_entity" in model.producer_context
        assert (
            model.producer_context["requires_manual_review"]
            == candidate.requires_manual_review
        )

        assert "generated_at" not in wire


class TestNewsDirectionMixedDoesNotLoseInformation:
    """News ``Direction`` has 4 values (positive/negative/neutral/mixed);
    contracts only has 3 (bullish/bearish/neutral). Mapper preserves
    ``mixed`` as ``producer_context["original_direction"] = "mixed"`` so
    Layer B replay/audit can reconstruct the news-local intent.
    """

    def test_mixed_direction_preserved_in_producer_context(self) -> None:
        from subsystem_news.contracts.candidates import (
            InvolvedEntity,
            NewsSignalCandidate,
        )
        from subsystem_news.contracts.evidence import EvidenceSpan
        from subsystem_news.contracts.source_reference import (
            SourceReference,
            SourceReferenceLocator,
        )
        from subsystem_news.runtime.submit import _validated_payload

        candidate = NewsSignalCandidate(
            candidate_id="mixed-direction-ex2",
            article_id="mixed-art",
            cluster_id=None,
            source_reference=SourceReference(
                source_id="mixed-source-A1",
                url="https://example-approved-news.com/a/mixed",
                provider_key=None,
                original_locator=SourceReferenceLocator(
                    locator_type="rss_guid",
                    locator_value="mixed-locator",
                ),
            ),
            signal_type="sentiment",
            direction="mixed",
            magnitude=0.5,
            affected_entities=[
                InvolvedEntity(
                    mention_text="Mixed Corp",
                    canonical_id="ENT_STOCK_MIXED_001",
                    resolution_status="resolved",
                    type_hint="company",
                ),
            ],
            impact_scope="company",
            time_horizon="short",
            rationale="placeholder",
            confidence=0.5,
            evidence_spans=[
                EvidenceSpan(
                    article_id="mixed-art",
                    start_char=0,
                    end_char=11,
                    quote="placeholder",
                    locator="body",
                ),
            ],
        )

        wire = _validated_payload(candidate)
        # Canonical wire direction is neutral (closest contracts.Direction
        # value), but original "mixed" lives in producer_context.
        assert wire["direction"] == "neutral"
        assert wire["producer_context"]["original_direction"] == "mixed"
