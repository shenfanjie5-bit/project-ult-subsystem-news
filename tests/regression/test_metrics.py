from __future__ import annotations

from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
    NewsSignalCandidate,
)
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference, SourceReferenceLocator
from subsystem_news.fixtures.catalog import (
    RegressionCaseResult,
    RegressionReport,
    RegressionThresholds,
)
from subsystem_news.fixtures.metrics import (
    compute_dedupe_precision,
    compute_evidence_coverage,
    compute_ex2_contract_completeness,
    compute_ex3_false_positive_rate,
)


def test_candidate_metric_functions_handle_contract_edges() -> None:
    complete_signal = _signal("signal-complete")
    incomplete_signal = NewsSignalCandidate.model_construct(
        candidate_id="signal-incomplete",
        article_id="article-metrics",
        cluster_id="cluster-metrics",
        source_reference=_source_reference(),
        evidence_spans=[_evidence()],
        export_contract="Ex-2",
        magnitude="medium",
        affected_entities=[],
    )
    missing_evidence = NewsFactCandidate.model_construct(
        candidate_id="fact-no-evidence",
        article_id="article-metrics",
        cluster_id="cluster-metrics",
        source_reference=_source_reference(),
        evidence_spans=[],
        export_contract="Ex-1",
    )

    assert compute_evidence_coverage([complete_signal, missing_evidence]) == 0.5
    assert compute_ex2_contract_completeness([complete_signal, incomplete_signal]) == 0.5


def test_report_metric_functions_use_case_results() -> None:
    report = RegressionReport(
        suite_id="metrics",
        suite_version="v1",
        thresholds=RegressionThresholds(),
        case_results=[
            RegressionCaseResult(
                case_id="repost-ok",
                category="repost_cluster",
                article_ids=["a", "b"],
                status="passed",
                baseline_path="baseline/repost.json",
                metrics={"dedupe_correct": 1.0},
            ),
            RegressionCaseResult(
                case_id="repost-bad",
                category="repost_cluster",
                article_ids=["c", "d"],
                status="failed",
                baseline_path="baseline/repost.json",
                metrics={"dedupe_correct": 0.0},
            ),
            RegressionCaseResult(
                case_id="negative-bad",
                category="graph_negative",
                article_ids=["e"],
                status="failed",
                baseline_path="baseline/negative.json",
                metrics={"ex3_candidate_count": 1.0},
            ),
            RegressionCaseResult(
                case_id="negative-ok",
                category="graph_negative",
                article_ids=["f"],
                status="passed",
                baseline_path="baseline/negative.json",
                metrics={"ex3_candidate_count": 0.0},
            ),
        ],
    )

    assert compute_dedupe_precision(report) == 0.5
    assert compute_ex3_false_positive_rate(report) == 0.5


def _source_reference() -> SourceReference:
    return SourceReference(
        source_id="metrics-source",
        url="https://metrics.example.com/article",
        provider_key="metrics-1",
        original_locator=SourceReferenceLocator(
            locator_type="fixture",
            locator_value="metrics-1",
        ),
    )


def _entity() -> InvolvedEntity:
    return InvolvedEntity(
        mention_text="Acme Corp",
        canonical_id="entity:acme-corp",
        resolution_status="resolved",
        type_hint="company",
    )


def _evidence() -> EvidenceSpan:
    return EvidenceSpan(
        article_id="article-metrics",
        start_char=0,
        end_char=9,
        quote="Acme Corp",
        locator="body",
    )


def _signal(candidate_id: str) -> NewsSignalCandidate:
    return NewsSignalCandidate(
        candidate_id=candidate_id,
        article_id="article-metrics",
        cluster_id="cluster-metrics",
        source_reference=_source_reference(),
        signal_type="event_impact",
        direction="positive",
        magnitude="medium",
        affected_entities=[_entity()],
        impact_scope="company",
        time_horizon="short",
        rationale="Metric fixture.",
        evidence_spans=[_evidence()],
        confidence=0.9,
    )
