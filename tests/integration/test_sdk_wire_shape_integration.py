"""Integration tier — END-TO-END subsystem-news ↔ subsystem-sdk
wire-shape integration test (the 7th issue per stage 2.9 plan template,
sibling of subsystem-announcement Stage 2.8 follow-up #3).

Goal: prove that news's REAL SDK adapter (``DefaultSubsystemSdkClient``)
routes through subsystem-sdk's ``validate_then_dispatch`` (which strips
SDK envelope at dispatch boundary per stage 2.7 follow-up #2) AND the
canonical wire payload passes ``contracts.Ex*.model_validate()`` after
strip.

For each Ex-1 / Ex-2 / Ex-3 we:

1. Build a real news candidate using the real candidate model
   constructor (no mocks — full pydantic validation).
2. Configure subsystem-sdk runtime with a ``BaseSubsystemContext``
   wrapping a ``SubmitClient(MockSubmitBackend)`` — using the SDK's
   default validator (NO permissive bypass).
3. Drive ``DefaultSubsystemSdkClient.submit([candidate])`` through:
       DefaultSubsystemSdkClient.submit
         → _validated_payload (canonical mapper)
         → subsystem_sdk.submit (top-level)
           → get_runtime().submit (= BaseSubsystemContext.submit)
             → SubmitClient.submit
               → validate_then_dispatch
                 → validate_payload (REAL contracts validation)
                 → strip_sdk_envelope(payload)   ← critical strip
                 → MockSubmitBackend.submit(wire_payload)
4. Assert ``backend.submitted_payloads[0]`` does NOT contain any SDK
   envelope field (``ex_type`` / ``semantic`` / ``produced_at``).
5. Assert canonical contracts.Ex* producer-owned fields reach the
   backend (subsystem_id / fact_id|signal_id|delta_id / entity_id|
   source_node|target_node / producer_context).
6. Assert the wire payload itself round-trips through real
   ``contracts.Ex*.model_validate()`` — defense in depth: if SDK strip
   ever drops too many fields, contracts will reject, this test fails.

If news ever refactors ``DefaultSubsystemSdkClient`` to call
``backend.submit`` directly (bypassing the SDK runtime), step 4 catches
it: the unstripped envelope reaches the recording backend.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from subsystem_sdk.backends.heartbeat import SubmitBackendHeartbeatAdapter
from subsystem_sdk.backends.mock import MockSubmitBackend
from subsystem_sdk.base import (
    BaseSubsystemContext,
    SubsystemRegistrationSpec,
    configure_runtime,
)
from subsystem_sdk.heartbeat.client import HeartbeatClient
from subsystem_sdk.submit.client import SubmitClient
from subsystem_sdk.validate.engine import SDK_ENVELOPE_FIELDS

from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import (
    SourceReference,
    SourceReferenceLocator,
)
from subsystem_news.runtime.submit import DefaultSubsystemSdkClient


# ── Helpers ────────────────────────────────────────────────────────


def _build_context_with_recording_backend(
    *,
    entity_lookup: Any | None = None,
    preflight_policy: str = "skip",
) -> tuple[
    BaseSubsystemContext, MockSubmitBackend
]:
    """Build a BaseSubsystemContext whose SubmitClient is wired to a
    MockSubmitBackend.

    The SubmitClient + HeartbeatClient use the SDK's DEFAULT validator
    (real ``validate_payload`` against ``contracts.Ex*.model_validate``).
    No permissive validator bypass.

    Registration spec mirrors what news's runtime would produce so the
    SDK's per-registration support check accepts the candidates we
    submit (Ex-0 + Ex-1 + Ex-2 + Ex-3).
    """

    backend = MockSubmitBackend()
    registration = SubsystemRegistrationSpec(
        subsystem_id="subsystem-news",
        version="0.1.1",
        domain="news",
        supported_ex_types=["Ex-0", "Ex-1", "Ex-2", "Ex-3"],
        owner="subsystem-news",
        heartbeat_policy_ref="interval:60s",
    )
    context = BaseSubsystemContext(
        registration=registration,
        submit_client=SubmitClient(
            backend,
            entity_lookup=entity_lookup,
            preflight_policy=preflight_policy,
        ),
        heartbeat_client=HeartbeatClient(SubmitBackendHeartbeatAdapter(backend)),
    )
    return context, backend


class RecordingLookup:
    def __init__(self, resolved_refs: Iterable[str] = ()) -> None:
        self._resolved_refs = set(resolved_refs)
        self.calls: list[tuple[str, ...]] = []

    def lookup(self, refs: Iterable[str]) -> Mapping[str, bool]:
        refs_tuple = tuple(refs)
        self.calls.append(refs_tuple)
        return {ref: ref in self._resolved_refs for ref in refs_tuple}


def _source_ref() -> SourceReference:
    return SourceReference(
        source_id="integ-source-A1",
        url="https://example-approved-news.com/integ/1",
        provider_key=None,
        original_locator=SourceReferenceLocator(
            locator_type="rss_guid",
            locator_value="integ-locator-001",
        ),
    )


def _entity(canonical_id: str = "ENT_STOCK_INTEG_001") -> InvolvedEntity:
    return InvolvedEntity(
        mention_text="Integ Corp",
        canonical_id=canonical_id,
        resolution_status="resolved",
        type_hint="company",
    )


def _evidence_span(
    *, start: int = 0, end: int = 11, locator: str = "title"
) -> EvidenceSpan:
    return EvidenceSpan(
        article_id="integ-art-001",
        start_char=start,
        end_char=end,
        quote="placeholder",
        locator=locator,
    )


# ── Ex-1 ──────────────────────────────────────────────────────────


class TestEx1FactCandidateThroughRealSdkAdapter:
    """Ex-1 candidate constructed via real NewsFactCandidate model +
    driven through real ``DefaultSubsystemSdkClient.submit`` —
    proves the wire-shape boundary holds AND the canonical mapper
    output passes real ``contracts.Ex1CandidateFact.model_validate``.
    """

    def test_ex1_news_adapter_strips_envelope_and_maps_to_canonical_shape(
        self,
    ) -> None:
        from contracts.schemas import Ex1CandidateFact

        candidate = NewsFactCandidate(
            candidate_id="integ-real-adapter-news-ex1",
            article_id="integ-art-001",
            cluster_id="integ-cluster-001",
            source_reference=_source_ref(),
            fact_type="contract",
            summary="placeholder integ summary",
            involved_entities=[_entity()],
            event_time=datetime(2026, 1, 1, tzinfo=UTC),
            confidence=0.91,
            source_reliability_tier="A",
            evidence_spans=[_evidence_span()],
        )

        context, backend = _build_context_with_recording_backend()
        with configure_runtime(context):
            receipt = DefaultSubsystemSdkClient().submit([candidate])

        assert receipt.accepted_count == 1, receipt
        assert receipt.rejected_count == 0
        assert receipt.submitted_candidate_ids == [candidate.candidate_id]

        assert len(backend.submitted_payloads) == 1
        wire = backend.submitted_payloads[0]
        leaked = SDK_ENVELOPE_FIELDS.intersection(wire)
        assert not leaked, (
            f"news -> SDK -> backend: SDK envelope leaked "
            f"{sorted(leaked)} (铁律 #7 wire-shape boundary)"
        )

        # Canonical contracts.Ex1 fields present.
        for field in (
            "subsystem_id",
            "fact_id",
            "entity_id",
            "fact_type",
            "fact_content",
            "confidence",
            "source_reference",
            "extracted_at",
            "evidence",
            "producer_context",
        ):
            assert field in wire, (
                f"required canonical Ex-1 field {field!r} missing: "
                f"{sorted(wire)}"
            )
        assert wire["subsystem_id"] == "subsystem-news"
        assert wire["entity_id"] == "ENT_STOCK_INTEG_001"

        # Defense in depth: round-trip the wire through real contracts.
        Ex1CandidateFact.model_validate(wire)

    def test_ex1_news_adapter_honors_sdk_block_preflight_before_backend(
        self,
    ) -> None:
        candidate = NewsFactCandidate(
            candidate_id="integ-preflight-news-ex1",
            article_id="integ-art-001",
            cluster_id="integ-cluster-001",
            source_reference=_source_ref(),
            fact_type="contract",
            summary="placeholder integ summary",
            involved_entities=[_entity("ENT_STOCK_PREFLIGHT_NEWS")],
            event_time=datetime(2026, 1, 1, tzinfo=UTC),
            confidence=0.91,
            source_reliability_tier="A",
            evidence_spans=[_evidence_span()],
        )
        lookup = RecordingLookup()
        context, backend = _build_context_with_recording_backend(
            entity_lookup=lookup,
            preflight_policy="block",
        )

        with configure_runtime(context):
            receipt = DefaultSubsystemSdkClient().submit([candidate])

        assert lookup.calls == [("ENT_STOCK_PREFLIGHT_NEWS",)]
        assert receipt.accepted_count == 0
        assert receipt.rejected_count == 1
        assert receipt.submitted_candidate_ids == []
        assert receipt.rejected_candidate_ids == [candidate.candidate_id]
        assert backend.submitted_payloads == ()


# ── Ex-2 ──────────────────────────────────────────────────────────


class TestEx2SignalCandidateThroughRealSdkAdapter:
    def test_ex2_news_adapter_strips_envelope_and_maps_to_canonical_shape(
        self,
    ) -> None:
        from contracts.schemas import Ex2CandidateSignal

        candidate = NewsSignalCandidate(
            candidate_id="integ-real-adapter-news-ex2",
            article_id="integ-art-001",
            cluster_id="integ-cluster-001",
            source_reference=_source_ref(),
            signal_type="event_impact",
            direction="positive",
            magnitude=0.7,
            affected_entities=[_entity()],
            impact_scope="company",
            time_horizon="short",
            rationale="placeholder integ rationale",
            confidence=0.85,
            evidence_spans=[_evidence_span(locator="body")],
        )

        context, backend = _build_context_with_recording_backend()
        with configure_runtime(context):
            receipt = DefaultSubsystemSdkClient().submit([candidate])

        assert receipt.accepted_count == 1, receipt
        wire = backend.submitted_payloads[0]
        leaked = SDK_ENVELOPE_FIELDS.intersection(wire)
        assert not leaked

        for field in (
            "subsystem_id",
            "signal_id",
            "signal_type",
            "direction",
            "magnitude",
            "affected_entities",
            "affected_sectors",
            "time_horizon",
            "evidence",
            "confidence",
            "producer_context",
        ):
            assert field in wire, (
                f"required canonical Ex-2 field {field!r} missing: "
                f"{sorted(wire)}"
            )
        # SignalDirection "positive" → contracts.Direction.bullish.
        assert wire["direction"] == "bullish"
        assert wire["affected_sectors"] == []
        assert "generated_at" not in wire

        Ex2CandidateSignal.model_validate(wire)


# ── Ex-3 ──────────────────────────────────────────────────────────


class TestEx3GraphDeltaCandidateThroughRealSdkAdapter:
    def test_ex3_news_adapter_strips_envelope_and_maps_to_canonical_shape(
        self,
    ) -> None:
        from contracts.schemas import Ex3CandidateGraphDelta

        candidate = NewsGraphDeltaCandidate(
            candidate_id="integ-real-adapter-news-ex3",
            article_id="integ-art-001",
            source_reference=_source_ref(),
            subject_entity=_entity("ENT_STOCK_INTEG_SRC"),
            relation_type="supplier_of",
            object_entity=_entity("ENT_STOCK_INTEG_DST"),
            delta_action="add",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            confidence=0.93,
            requires_manual_review=True,
            evidence_spans=[
                _evidence_span(),
                _evidence_span(start=20, end=35, locator="body"),
            ],
        )

        context, backend = _build_context_with_recording_backend()
        with configure_runtime(context):
            receipt = DefaultSubsystemSdkClient().submit([candidate])

        assert receipt.accepted_count == 1, receipt
        wire = backend.submitted_payloads[0]
        leaked = SDK_ENVELOPE_FIELDS.intersection(wire)
        assert not leaked

        for field in (
            "subsystem_id",
            "delta_id",
            "delta_type",
            "source_node",
            "target_node",
            "relation_type",
            "properties",
            "evidence",
            "producer_context",
        ):
            assert field in wire, (
                f"required canonical Ex-3 field {field!r} missing: "
                f"{sorted(wire)}"
            )
        assert wire["delta_type"] == "add"
        assert wire["relation_type"] == "supplier_of"
        assert wire["source_node"] == "ENT_STOCK_INTEG_SRC"
        assert wire["target_node"] == "ENT_STOCK_INTEG_DST"
        # Schema enforces non-empty evidence; news provides 2 for Ex-3.
        assert len(wire["evidence"]) == 2
        assert "generated_at" not in wire

        Ex3CandidateGraphDelta.model_validate(wire)


# ── Defense check: prove the strip path detects a regression ──────


class TestRegressionDetectionDefenseCheck:
    """Sanity check: if SDK_ENVELOPE_FIELDS ever shrinks (e.g. someone
    drops produced_at from the strip set without coordinating with
    news), this test surfaces it. The wire-shape boundary in news
    boundary tests + this integration test depend on the same
    SDK_ENVELOPE_FIELDS constant — lock it.
    """

    def test_envelope_set_canonical_definition_holds(self) -> None:
        assert SDK_ENVELOPE_FIELDS == frozenset(
            {"ex_type", "semantic", "produced_at"}
        ), (
            f"SDK_ENVELOPE_FIELDS drifted: got "
            f"{sorted(SDK_ENVELOPE_FIELDS)}; expected "
            "{ex_type, semantic, produced_at}. news's wire-shape "
            "boundary tests assume this exact 3-field set."
        )
