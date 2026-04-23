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
runs news's full Ex-3 derivation chain — ``extract_graph_deltas`` →
``build_graph_delta_candidate`` → ``validate_graph_evidence`` (NOT
just the submit-side ``_validate_candidate``, which is a downstream
belt-and-suspenders check). Stage 2.9 follow-up #1 (codex review #1
P2 #3): the previous version of this test only invoked
``_validate_candidate`` and would still have stayed green if a bug
in ``extract_graph_deltas`` / ``validate_graph_evidence`` let weak
candidates through. Now it exercises the real production guard chain.

Fixture: ``audit_eval_fixtures.event_cases.case_ex3_negative``
(audit-eval v0.2.2 release; same case used by subsystem-announcement
Stage 2.8 follow-up #3 regression). The case is stock-exchange
announcement-shaped, but its **business expectation is shape-
neutral**: given weak evidence + non-official source + unresolved
downstream entity, the high-threshold guard MUST emit 0 Ex-3
candidates.

Translation announcement → news:
- announcement ``source_reference.is_primary_source=False`` (forum
  redistribution) → news ``article.reliability_tier="C"``, which
  ``validate_graph_evidence`` rejects as non-high-reliability.
- announcement ``confidence=0.35`` (single weak evidence) → news
  draft ``confidence=0.35``, which ``extract_graph_deltas`` filters
  via ``min_confidence=0.75`` default before reaching
  ``validate_graph_evidence``.
- announcement ``ENT_UNRESOLVED_DOWNSTREAM_PARTNER`` (unresolved
  target) → news ``EntityResolutionResult`` lists ONLY the resolved
  subject entity; an unresolved object can't pass
  ``build_graph_delta_candidate``'s entity_resolution allowlist
  check, so the candidate is dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

# Iron rule #1: hard import. Missing audit_eval_fixtures must fail
# collection — NOT module-level skip.
from audit_eval_fixtures import load_case  # noqa: F401  (load_case below proves use)

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
)
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import (
    SourceReference,
    SourceReferenceLocator,
)
from subsystem_news.entities.mention import Mention
from subsystem_news.entities.resolution import (
    EntityResolutionResult,
    ResolvedMention,
)
from subsystem_news.graph import extract_graph_deltas


class _RecordingReasonerRuntimeClient:
    """Stub ReasonerRuntimeClient that returns one fixed graph_deltas
    response. ``extract_graph_deltas`` calls
    ``client.generate_structured(request)`` once per article-cluster
    pair; we hand back the case_ex3_negative-shaped draft and observe
    the guard chain reject it."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[Any] = []

    def generate_structured(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return self.response


def _build_subject_entity() -> InvolvedEntity:
    """The single resolved entity in the fixture scenario (announcement-
    side ENT_STOCK_300750.SZ → news-side resolved subject)."""

    return InvolvedEntity(
        mention_text="宁德时代",
        canonical_id="ENT_STOCK_300750.SZ",
        resolution_status="resolved",
        type_hint="company",
    )


def _build_unresolved_object_entity() -> InvolvedEntity:
    """The unresolved counterparty (announcement-side
    ENT_UNRESOLVED_DOWNSTREAM_PARTNER → news-side unresolved object)."""

    return InvolvedEntity(
        mention_text="某下游厂商",
        canonical_id=None,
        resolution_status="unresolved",
        type_hint="company",
    )


def _build_news_inputs(
    *, reliability_tier: str
) -> tuple[
    NewsArticleArtifact,
    NewsDedupeCluster,
    EntityResolutionResult,
    list[NewsFactCandidate],
]:
    """News-shape (article, cluster, entity_resolution, facts) tuple
    that mirrors the fixture's announcement scenario.

    ``reliability_tier="C"`` reproduces the fixture's "non_official_
    source" guard reason (forum redistribution); the
    ``EntityResolutionResult`` lists ONLY the resolved subject (no
    object) reproducing the "unresolved_target_entity_anchor" guard
    reason.
    """

    body_text = (
        "据某社区论坛转载报道：宁德时代或将与某下游厂商终止现有供货合同，"
        "市场猜测涉及金额可能在亿级；具体合同条款、终止时间、双方主体均未公开披露。"
    )
    source_reference = SourceReference(
        source_id="forum-redistribution-source",
        url="http://forum.example.com/announcements/redistributed/300750/2026-04-18-supplier-shift",
        provider_key="forum-redistribution",
        original_locator=SourceReferenceLocator(
            locator_type="forum_thread",
            locator_value="2026-04-18-supplier-shift",
        ),
    )
    article = NewsArticleArtifact(
        article_id="news-art-from-case-ex3-negative",
        source_id="forum-redistribution-source",
        source_reference=source_reference,
        title="供货合同传闻",
        body_text=body_text,
        published_at=datetime(2026, 4, 18, tzinfo=UTC),
        fetched_at=datetime(2026, 4, 18, 0, 5, tzinfo=UTC),
        language="zh",
        author_or_channel="forum redistributor",
        content_hash="sha256:case-ex3-neg-news",
        article_fingerprint="sha256:case-ex3-neg-news-fp",
        license_tag="forum",
        reliability_tier=reliability_tier,
        cluster_id="cluster-news-case-ex3-negative",
    )
    cluster = NewsDedupeCluster(
        cluster_id="cluster-news-case-ex3-negative",
        representative_article_id=article.article_id,
        member_article_ids=[article.article_id],
        canonical_headline=article.title,
        first_published_at=article.published_at,
        source_count=1,
        fingerprint_family="sha256:case-ex3-neg-family",
        cluster_confidence=0.50,
    )
    subject = _build_subject_entity()
    subject_mention = Mention(
        article_id=article.article_id,
        text=subject.mention_text,
        start_char=body_text.index(subject.mention_text),
        end_char=(
            body_text.index(subject.mention_text) + len(subject.mention_text)
        ),
        locator="body",
        type_hint=subject.type_hint,
        context=body_text,
        source_reference=source_reference,
    )
    # Critical: entity_resolution lists ONLY the resolved subject.
    # The object entity is "unresolved" (no canonical_id) and is NOT
    # in the resolution result, so build_graph_delta_candidate's
    # entity-allowlist check rejects any draft pointing at it.
    entity_resolution = EntityResolutionResult(
        mentions=[subject_mention],
        resolved_mentions=[
            ResolvedMention(
                mention=subject_mention,
                entity=subject,
                resolution_source="registry",
                registry_resolution=None,
            ),
        ],
        entities=[subject],
    )
    fact = NewsFactCandidate(
        candidate_id="fact-news-case-ex3-negative",
        article_id=article.article_id,
        cluster_id=cluster.cluster_id,
        source_reference=source_reference,
        fact_type="contract",
        summary="rumored supply contract termination",
        involved_entities=[subject],
        event_time=datetime(2026, 4, 18, tzinfo=UTC),
        confidence=0.35,
        source_reliability_tier=reliability_tier,
        evidence_spans=[
            EvidenceSpan(
                article_id=article.article_id,
                start_char=14,
                end_char=36,
                quote="宁德时代或将与某下游厂商终止现有供货合同",
                locator="body",
            ),
        ],
    )
    return article, cluster, entity_resolution, [fact]


def _draft_pointing_at_unresolved_object(
    article: NewsArticleArtifact, *, confidence: float
) -> dict[str, Any]:
    """Build a graph_deltas draft entry that mirrors the fixture's
    ``candidate_graph_delta_attempt`` (subject resolved + object
    unresolved + supplier_of relation + 1 weak evidence quote).
    """

    subject = _build_subject_entity()
    unresolved_object = _build_unresolved_object_entity()
    return {
        "subject_entity": subject.model_dump(mode="json"),
        "relation_type": "supplier_of",
        "object_entity": unresolved_object.model_dump(mode="json"),
        "delta_action": "deactivate",
        "valid_from": None,
        "confidence": confidence,
        "requires_manual_review": True,
        "evidence_spans": [
            {
                "article_id": article.article_id,
                "start_char": 14,
                "end_char": 36,
                "quote": "宁德时代或将与某下游厂商终止现有供货合同",
                "locator": "body",
            },
        ],
    }


class TestEx3HighThresholdGuardRejectsCaseNegativeViaRealGuardChain:
    """Iron rule #5 + main-core sub-rule: real runtime + fixture-derived
    business expectation. Stage 2.9 follow-up #1 (codex review #1 P2 #3)
    upgrade: this test now drives the FULL real guard chain
    (``extract_graph_deltas`` → ``build_graph_delta_candidate`` →
    ``validate_graph_evidence``), not the submit-side
    ``_validate_candidate`` shortcut. A bug anywhere in the real chain
    that lets the case_ex3_negative draft through would now fail this
    test.

    Fixture ``case_ex3_negative`` business contract: 0 Ex-3 emitted.
    """

    def test_low_confidence_filtered_before_reaching_evidence_guard(
        self,
    ) -> None:
        """Fixture confidence=0.35 < default min_confidence=0.75. The
        draft must be filtered by ``extract_graph_deltas``'s
        per-draft confidence gate, BEFORE
        ``build_graph_delta_candidate`` / ``validate_graph_evidence``
        even see it. Result: 0 candidates.
        """

        case = load_case("event_cases", "case_ex3_negative")
        expected = case.expected
        assert expected["ex3_candidates_emitted"] == 0
        assert "single_weak_evidence" in expected["guard_reasons"]

        article, cluster, entity_resolution, facts = _build_news_inputs(
            reliability_tier="A"  # so confidence is the only rejection axis
        )
        client = _RecordingReasonerRuntimeClient(
            response={
                "graph_deltas": [
                    _draft_pointing_at_unresolved_object(
                        article, confidence=0.35
                    )
                ]
            }
        )

        candidates = extract_graph_deltas(
            article,
            cluster,
            entity_resolution,
            facts,
            client,
        )

        assert candidates == [], (
            f"case_ex3_negative business contract: 0 Ex-3 emitted; "
            f"got {len(candidates)} via real guard chain"
        )
        # Confirm the reasoner client was actually called (proves
        # extract_graph_deltas reached the real guard chain rather
        # than short-circuiting on empty input).
        assert len(client.requests) == 1

    def test_unresolved_target_entity_rejected_at_candidate_builder(
        self,
    ) -> None:
        """Even at high confidence, the draft's unresolved object_entity
        is NOT in entity_resolution.entities, so
        ``build_graph_delta_candidate`` returns None (entity-allowlist
        check). Result: 0 candidates.
        """

        case = load_case("event_cases", "case_ex3_negative")
        assert (
            "unresolved_target_entity_anchor"
            in case.expected["guard_reasons"]
        )

        article, cluster, entity_resolution, facts = _build_news_inputs(
            reliability_tier="A"
        )
        client = _RecordingReasonerRuntimeClient(
            response={
                "graph_deltas": [
                    # Confidence ABOVE the min_confidence floor so the
                    # filter doesn't catch it — let the entity-allowlist
                    # check do the rejection.
                    _draft_pointing_at_unresolved_object(
                        article, confidence=0.92
                    )
                ]
            }
        )

        candidates = extract_graph_deltas(
            article,
            cluster,
            entity_resolution,
            facts,
            client,
        )

        assert candidates == [], (
            "case_ex3_negative target-entity-anchor business contract: "
            f"0 Ex-3 emitted; got {len(candidates)} via real "
            "build_graph_delta_candidate entity-allowlist gate"
        )

    def test_non_official_source_rejected_at_evidence_guard(self) -> None:
        """If we cheat past the entity-allowlist check by listing the
        object in entity_resolution AND go past the confidence filter,
        the article's ``reliability_tier="C"`` (mirroring the fixture's
        "non_official_source" guard reason — forum redistribution) must
        still cause ``validate_graph_evidence`` to reject. Result: 0
        candidates.
        """

        case = load_case("event_cases", "case_ex3_negative")
        assert "non_official_source" in case.expected["guard_reasons"]

        article, cluster, entity_resolution, facts = _build_news_inputs(
            reliability_tier="C"
        )
        # Promote object_entity to "resolved" + add to entity_resolution
        # so ONLY the reliability_tier="C" axis is left for rejection.
        # This mirrors a worst-case where entity-registry mistakenly
        # resolves a forum-rumored counterparty to a real ENT_*; the
        # source-reliability guard is the last line of defense.
        object_entity = InvolvedEntity(
            mention_text="某下游厂商",
            canonical_id="ENT_STOCK_HYPOTHETICAL_COUNTERPARTY",
            resolution_status="resolved",
            type_hint="company",
        )
        object_mention = Mention(
            article_id=article.article_id,
            text=object_entity.mention_text,
            start_char=article.body_text.index(object_entity.mention_text),
            end_char=(
                article.body_text.index(object_entity.mention_text)
                + len(object_entity.mention_text)
            ),
            locator="body",
            type_hint=object_entity.type_hint,
            context=article.body_text,
            source_reference=article.source_reference,
        )
        entity_resolution = EntityResolutionResult(
            mentions=[*entity_resolution.mentions, object_mention],
            resolved_mentions=[
                *entity_resolution.resolved_mentions,
                ResolvedMention(
                    mention=object_mention,
                    entity=object_entity,
                    resolution_source="registry",
                    registry_resolution=None,
                ),
            ],
            entities=[*entity_resolution.entities, object_entity],
        )
        client = _RecordingReasonerRuntimeClient(
            response={
                "graph_deltas": [
                    {
                        **_draft_pointing_at_unresolved_object(
                            article, confidence=0.92
                        ),
                        # Override object_entity with the resolved version
                        # so this test isolates the reliability_tier axis.
                        "object_entity": object_entity.model_dump(mode="json"),
                    }
                ]
            }
        )

        candidates = extract_graph_deltas(
            article,
            cluster,
            entity_resolution,
            facts,
            client,
        )

        assert candidates == [], (
            "case_ex3_negative non-official-source business contract: "
            f"0 Ex-3 emitted; got {len(candidates)} via real "
            "validate_graph_evidence reliability_tier guard"
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
