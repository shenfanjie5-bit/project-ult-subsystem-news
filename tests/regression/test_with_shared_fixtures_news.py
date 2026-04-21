"""Stage 2.9 regression tier — fixture-backed regression via
audit_eval_fixtures (sibling of subsystem-announcement Stage 2.8
follow-up #3 ``case_ex3_negative`` regression).

CLAUDE.md (subsystem-news):
- §10 #7 (Ex-3 high threshold): only allow Ex-3 emission with
  explicit relation evidence; no co-occurrence / sentiment-derived
  relation edges.
- §19 (KPI): Ex-3 false positive rate <= 1%.

This regression hard-imports ``audit_eval_fixtures`` (iron rule #1 — no
``pytest.skip(allow_module_level=True)``; missing fixture pack must
fail collection so dev-only venvs surface the gap loudly). It really
runs news's runtime ``_validate_candidate`` (NOT just inspects fixture
JSON — iron rule #5 + main-core sub-rule "real runtime + fixture-
derived business expectation").

Fixture: ``audit_eval_fixtures.event_cases.case_ex3_negative``
(audit-eval v0.2.2 release; same case used by subsystem-announcement
Stage 2.8 follow-up #3 regression). The case is stock-exchange
announcement-shaped, but its **business expectation is shape-
neutral**: given weak evidence + non-official source + unresolved
downstream entity, the high-threshold guard MUST emit 0 Ex-3
candidates. We translate the announcement-shaped input into news's
``NewsGraphDeltaCandidate`` shape and assert news's
``_require_graph_fields`` rejects it (the news-side analog of
announcement's ``_graph_delta_guard``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# Iron rule #1: hard import. Missing audit_eval_fixtures must fail
# collection — NOT module-level skip.
from audit_eval_fixtures import load_case  # noqa: F401  (load_case below proves use)

from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsGraphDeltaCandidate,
)
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import (
    SourceReference,
    SourceReferenceLocator,
)
from subsystem_news.errors import ContractViolationError
from subsystem_news.runtime.submit import _validate_candidate


class TestEx3HighThresholdGuardRejectsWeakEvidence:
    """Iron rule #5 + main-core sub-rule: real runtime + fixture-derived
    business expectation.

    Fixture ``case_ex3_negative`` declares the high-threshold guard MUST
    emit 0 Ex-3 candidates given the weak/non-official scenario. News's
    analog of the guard is ``_require_graph_fields`` which rejects
    Ex-3 candidates whose subject_entity / object_entity is not
    ``resolved`` (i.e. has ``canonical_id is None``). Drive the
    fixture's scenario through ``_validate_candidate`` and assert the
    expected business outcome (rejection with explicit reason).
    """

    def test_unresolved_target_entity_anchor_rejects_ex3(self) -> None:
        case = load_case("event_cases", "case_ex3_negative")

        # Pull the business expectation out of the fixture (NOT
        # inspecting fixture JSON — using it to derive the test
        # invariants).
        expected = case.expected
        assert expected["ex3_candidates_emitted"] == 0, (
            f"fixture business contract drift: case_ex3_negative now "
            f"expects {expected['ex3_candidates_emitted']} Ex-3 candidates "
            "(expected exact 0)"
        )
        assert expected["ex3_high_threshold_guard_triggered"] is True
        assert "unresolved_target_entity_anchor" in expected["guard_reasons"]

        # Translate the fixture's "candidate_graph_delta_attempt" into
        # news's NewsGraphDeltaCandidate shape, preserving the
        # business-essential bits:
        # - subject_entity is resolvable (announcement-side
        #   ENT_STOCK_300750_SZ); we map to news's resolved subject.
        # - target_node is unresolved (announcement-side
        #   ENT_UNRESOLVED_DOWNSTREAM_PARTNER) → news's unresolved
        #   object_entity (canonical_id=None,
        #   resolution_status="unresolved").
        # - evidence is single weak (forum redistribution); news's
        #   schema requires non-empty evidence_spans, so we provide
        #   2 minimal weak spans.
        attempt = case.input["candidate_graph_delta_attempt"]
        ex3_candidate = NewsGraphDeltaCandidate(
            candidate_id="news-ex3-from-case-ex3-negative",
            article_id="news-art-from-case-ex3-negative",
            source_reference=SourceReference(
                source_id="non-official-source-from-fixture",
                # Fixture says non-official redistribution (forum) —
                # news's source_reference here mirrors that intent.
                url=case.input["source_reference"]["url"],
                provider_key=None,
                original_locator=SourceReferenceLocator(
                    locator_type="forum_url",
                    locator_value=str(attempt.get("delta_id", "delta-x")),
                ),
            ),
            subject_entity=InvolvedEntity(
                mention_text="Subject Anchor",
                canonical_id=str(attempt["source_node"]),
                resolution_status="resolved",
                type_hint="company",
            ),
            relation_type="supplier_of",
            object_entity=InvolvedEntity(
                # Announcement-side ENT_UNRESOLVED_DOWNSTREAM_PARTNER →
                # news-side unresolved entity (canonical_id=None).
                mention_text="某下游厂商",
                canonical_id=None,
                resolution_status="unresolved",
                type_hint="company",
            ),
            delta_action="deactivate",
            valid_from=datetime(2026, 4, 18, tzinfo=UTC),
            confidence=0.35,
            requires_manual_review=True,
            evidence_spans=[
                EvidenceSpan(
                    article_id="news-art-from-case-ex3-negative",
                    start_char=14,
                    end_char=36,
                    quote="terminate existing supply contract (rumor)",
                    locator="body",
                ),
                EvidenceSpan(
                    article_id="news-art-from-case-ex3-negative",
                    start_char=37,
                    end_char=70,
                    quote="downstream partner identity not disclosed",
                    locator="body",
                ),
            ],
        )

        # Real runtime touch (iron rule #5): _validate_candidate (which
        # delegates to _require_graph_fields for Ex-3) MUST reject this
        # candidate — the high-threshold guard's business outcome.
        with pytest.raises(ContractViolationError) as excinfo:
            _validate_candidate(ex3_candidate)

        # Fixture-derived business expectation (iron rule #5 main-core
        # sub-rule): the rejection reason must name the unresolved
        # entity anchor (matching the fixture's
        # "unresolved_target_entity_anchor" guard_reason).
        msg = str(excinfo.value).lower()
        assert "object_entity" in msg or "object" in msg, (
            f"news ex3 guard rejection reason should mention the "
            f"unresolved entity anchor; got {msg!r}"
        )
        assert "resolved" in msg or "canonical_id" in msg, (
            f"news ex3 guard rejection reason should reference "
            f"resolution_status / canonical_id; got {msg!r}"
        )


class TestFixtureMetadataAcknowledgesNewsConsumer:
    """Cross-check the fixture's metadata declares ``subsystem-news`` as
    a consumer (audit-eval v0.2.2 explicitly added the case for
    subsystem-announcement Stage 2.8 follow-up #3 + listed news as a
    secondary consumer). If a future audit-eval bump removes news from
    consumers, this regression should be revisited.
    """

    def test_case_ex3_negative_lists_news_in_consumers(self) -> None:
        case = load_case("event_cases", "case_ex3_negative")
        metadata = case.metadata

        primary = metadata.get("primary_consumer")
        secondary = metadata.get("secondary_consumers") or []
        all_consumers = {primary, *secondary}
        assert "subsystem-news" in all_consumers, (
            f"audit-eval v0.2.2 case_ex3_negative metadata should "
            f"include subsystem-news as a consumer; got primary="
            f"{primary!r}, secondary={secondary!r}"
        )

        assert metadata.get("fixture_kind") == "ex3_high_threshold_negative", (
            f"fixture kind drift: expected "
            f"'ex3_high_threshold_negative', got "
            f"{metadata.get('fixture_kind')!r}"
        )
