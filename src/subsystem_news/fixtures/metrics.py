"""Regression metrics for fixture replay reports."""

from __future__ import annotations

from collections.abc import Sequence

from subsystem_news.runtime.models import CandidatePayload
from subsystem_news.fixtures.catalog import RegressionReport


def compute_evidence_coverage(candidates: Sequence[CandidatePayload]) -> float:
    """Return the share of candidates with at least one evidence span."""

    if not candidates:
        return 1.0
    covered = sum(1 for candidate in candidates if candidate.evidence_spans)
    return covered / len(candidates)


def compute_dedupe_precision(report: RegressionReport) -> float:
    """Return curated repost precision from per-case regression metrics."""

    repost_cases = [
        result for result in report.case_results if result.category == "repost_cluster"
    ]
    if not repost_cases:
        return 1.0
    scores = [
        result.metrics.get(
            "dedupe_precision",
            result.metrics.get("dedupe_correct", 0.0),
        )
        for result in repost_cases
    ]
    return sum(scores) / len(scores)


def compute_unresolved_explicitness(report: RegressionReport) -> float:
    """Return the share of unresolved expected entities preserved explicitly."""

    total = 0
    explicit = 0
    for result in report.case_results:
        for output in result.expected_outputs:
            entities = [
                *output.involved_entities,
                *output.affected_entities,
                *(
                    [output.subject_entity]
                    if output.subject_entity is not None
                    else []
                ),
                *(
                    [output.object_entity]
                    if output.object_entity is not None
                    else []
                ),
            ]
            for entity in entities:
                if entity.resolution_status not in {"unresolved", "ambiguous"}:
                    continue
                total += 1
                if entity.canonical_id is None:
                    explicit += 1
    if total == 0:
        return 1.0
    return explicit / total


def compute_ex2_contract_completeness(candidates: Sequence[CandidatePayload]) -> float:
    """Return the share of Ex-2 candidates with required contract fields."""

    signals = [
        candidate for candidate in candidates if candidate.export_contract == "Ex-2"
    ]
    if not signals:
        return 1.0
    complete = sum(
        1
        for signal in signals
        if getattr(signal, "direction", None) is not None
        and getattr(signal, "magnitude", None) not in {None, ""}
        and bool(getattr(signal, "affected_entities", None))
    )
    return complete / len(signals)


def compute_ex3_false_positive_rate(report: RegressionReport) -> float:
    """Return Ex-3 false-positive rate across reviewed negative cases."""

    negative_cases = [
        result for result in report.case_results if result.category == "graph_negative"
    ]
    if not negative_cases:
        return 0.0
    false_positive_cases = sum(
        1
        for result in negative_cases
        if result.metrics.get(
            "ex3_false_positive_count",
            result.metrics.get("ex3_candidate_count", 0.0),
        )
        > 0.0
    )
    return false_positive_cases / len(negative_cases)


__all__ = [
    "compute_dedupe_precision",
    "compute_evidence_coverage",
    "compute_ex2_contract_completeness",
    "compute_ex3_false_positive_rate",
    "compute_unresolved_explicitness",
]
