"""Regression fixture suite runner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from subsystem_news.contracts.candidates import (
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.errors import ContractViolationError
from subsystem_news.fixtures.catalog import (
    FixtureCase,
    FixtureSuite,
    RegressionCaseResult,
    RegressionReport,
    RegressionThresholds,
)
from subsystem_news.fixtures.loader import validate_fixture_suite
from subsystem_news.fixtures.metrics import (
    compute_dedupe_precision,
    compute_evidence_coverage,
    compute_ex2_contract_completeness,
    compute_ex3_false_positive_rate,
)
from subsystem_news.runtime.models import CandidatePayload
from subsystem_news.runtime.replay import (
    ReplayRequest,
    ReplayResult,
    diff_replay_results,
    replay_article,
)


def run_regression_suite(
    suite: FixtureSuite,
    *,
    thresholds: RegressionThresholds,
    replay_runner: Callable[[ReplayRequest], ReplayResult] = replay_article,
) -> RegressionReport:
    """Run the checked-in fixture suite through the provided replay runner."""

    validate_fixture_suite(suite)
    case_results: list[RegressionCaseResult] = []
    all_candidates: list[CandidatePayload] = []

    for case in suite.cases:
        case_result, case_candidates = _run_case(case, suite, replay_runner)
        case_results.append(case_result)
        all_candidates.extend(case_candidates)

    provisional = RegressionReport(
        suite_id=suite.suite_id,
        suite_version=suite.suite_version,
        generated_at=datetime.now(timezone.utc),
        thresholds=thresholds,
        case_results=case_results,
        metrics={},
        threshold_violations=[],
        passed=False,
    )
    metrics = {
        "evidence_coverage": _evidence_coverage_from_replayed(
            case_results,
            all_candidates,
        ),
        "dedupe_precision": compute_dedupe_precision(provisional),
        "unresolved_explicitness": _unresolved_explicitness_from_replayed(
            case_results,
            all_candidates,
        ),
        "ex2_contract_completeness": _ex2_completeness_from_replayed(
            case_results,
            all_candidates,
        ),
        "ex3_false_positive_rate": compute_ex3_false_positive_rate(provisional),
    }
    violations = _threshold_violations(metrics, thresholds)
    failed_cases = [result.case_id for result in case_results if result.status == "failed"]
    violations.extend(f"case failed: {case_id}" for case_id in failed_cases)
    return provisional.model_copy(
        update={
            "metrics": metrics,
            "threshold_violations": violations,
            "passed": not violations,
        }
    )


def _run_case(
    case: FixtureCase,
    suite: FixtureSuite,
    replay_runner: Callable[[ReplayRequest], ReplayResult],
) -> tuple[RegressionCaseResult, list[CandidatePayload]]:
    baseline_path = case.resolved_baseline_path(suite.root_path)
    request = ReplayRequest(
        case_id=case.case_id,
        category=case.category,
        article_ids=list(case.article_ids),
        input_path=baseline_path,
        baseline_path=baseline_path,
        metadata={"expected_cluster_id": case.expected_cluster_id},
    )
    try:
        baseline = replay_article(request)
        replayed = replay_runner(request)
        diff = diff_replay_results(baseline, replayed)
        candidates = _case_candidate_payloads(
            case,
            _candidate_payloads_from_result(replayed),
        )
        missing_candidate_payloads = _missing_candidate_payloads(case, candidates)
        expected_output_mismatch = _expected_output_mismatch(case, candidates)
        metrics = _case_metrics(
            case,
            diff=diff,
            candidates=candidates,
            missing_candidate_payloads=missing_candidate_payloads,
            expected_output_mismatch=expected_output_mismatch,
        )
        status = (
            "failed"
            if (
                diff.has_changes
                or replayed.error_count
                or missing_candidate_payloads
                or expected_output_mismatch
            )
            else "passed"
        )
        return (
            RegressionCaseResult(
                case_id=case.case_id,
                category=case.category,
                article_ids=list(case.article_ids),
                status=status,
                baseline_path=str(baseline_path),
                expected_outputs=list(case.expected_outputs),
                replay_diff=diff,
                metrics=metrics,
                metadata={
                    "expected_cluster_id": case.expected_cluster_id,
                    "missing_candidate_payloads": missing_candidate_payloads,
                    "expected_output_mismatch": expected_output_mismatch,
                    **case.metadata,
                },
            ),
            candidates,
        )
    except Exception as exc:  # noqa: BLE001 - regression reports should expose all failures.
        return (
            RegressionCaseResult(
                case_id=case.case_id,
                category=case.category,
                article_ids=list(case.article_ids),
                status="failed",
                baseline_path=str(baseline_path),
                expected_outputs=list(case.expected_outputs),
                replay_error=f"{exc.__class__.__name__}: {exc}",
                metrics=_case_metrics(
                    case,
                    diff=None,
                    candidates=[],
                    missing_candidate_payloads=_case_expects_candidates(case),
                    expected_output_mismatch=_case_expects_candidates(case),
                ),
                metadata={
                    "expected_cluster_id": case.expected_cluster_id,
                    "missing_candidate_payloads": _case_expects_candidates(case),
                    "expected_output_mismatch": _case_expects_candidates(case),
                    **case.metadata,
                },
            ),
            [],
        )


def _case_metrics(
    case: FixtureCase,
    *,
    diff: Any,
    candidates: list[CandidatePayload],
    missing_candidate_payloads: bool,
    expected_output_mismatch: bool,
) -> dict[str, float]:
    outputs = list(case.expected_outputs)
    ex3_count = sum(1 for candidate in candidates if candidate.export_contract == "Ex-3")

    dedupe_correct = 1.0
    if case.category == "repost_cluster":
        article_ids = set(case.article_ids)
        replayed_article_ids = {candidate.article_id for candidate in candidates}
        cluster_ids = {
            candidate.cluster_id
            for candidate in candidates
            if getattr(candidate, "cluster_id", None) is not None
        }
        dedupe_correct = (
            1.0
            if candidates
            and article_ids.issubset(replayed_article_ids)
            and len(cluster_ids) == 1
            else 0.0
        )
        if diff is not None and getattr(diff, "candidate_diffs", None):
            dedupe_correct = 0.0

    return {
        "expected_candidate_count": float(len(outputs)),
        "actual_candidate_count": float(len(candidates)),
        "expected_ex2_count": float(
            sum(1 for output in outputs if output.export_contract == "Ex-2")
        ),
        "actual_ex2_count": float(
            sum(1 for candidate in candidates if candidate.export_contract == "Ex-2")
        ),
        "expected_ex3_count": float(
            sum(1 for output in outputs if output.export_contract == "Ex-3")
        ),
        "actual_ex3_count": float(ex3_count),
        "ex3_candidate_count": float(ex3_count),
        "missing_candidate_payloads": 1.0 if missing_candidate_payloads else 0.0,
        "expected_output_mismatch": 1.0 if expected_output_mismatch else 0.0,
        "dedupe_correct": dedupe_correct,
    }


def _case_candidate_payloads(
    case: FixtureCase,
    candidates: list[CandidatePayload],
) -> list[CandidatePayload]:
    article_ids = set(case.article_ids)
    return [
        candidate for candidate in candidates if candidate.article_id in article_ids
    ]


def _candidate_payloads_from_result(result: ReplayResult) -> list[CandidatePayload]:
    payloads = result.metadata.get("candidate_payloads")
    if payloads is None:
        return []
    if not isinstance(payloads, list):
        raise ContractViolationError("candidate_payloads must be a list")
    candidates: list[CandidatePayload] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            raise ContractViolationError("candidate_payloads entries must be objects")
        candidates.append(_candidate_from_payload(payload))
    return candidates


def _candidate_from_payload(payload: dict[str, Any]) -> CandidatePayload:
    try:
        contract = payload.get("export_contract")
        if contract == "Ex-1":
            return NewsFactCandidate.model_validate(payload)
        if contract == "Ex-2":
            return NewsSignalCandidate.model_validate(payload)
        if contract == "Ex-3":
            return NewsGraphDeltaCandidate.model_validate(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ContractViolationError("candidate payload violates Ex contract") from exc
    raise ContractViolationError("candidate payload missing supported export_contract")


def _missing_candidate_payloads(
    case: FixtureCase,
    candidates: list[CandidatePayload],
) -> bool:
    return _case_expects_candidates(case) and not candidates


def _case_expects_candidates(case: FixtureCase) -> bool:
    return bool(case.expected_outputs)


def _expected_output_mismatch(
    case: FixtureCase,
    candidates: list[CandidatePayload],
) -> bool:
    expected_ids = {output.candidate_id for output in case.expected_outputs}
    actual_ids = {candidate.candidate_id for candidate in candidates}
    return expected_ids != actual_ids


def _evidence_coverage_from_replayed(
    case_results: list[RegressionCaseResult],
    candidates: list[CandidatePayload],
) -> float:
    if candidates:
        return compute_evidence_coverage(candidates)
    if _results_expect_candidates(case_results):
        return 0.0
    return compute_evidence_coverage(candidates)


def _ex2_completeness_from_replayed(
    case_results: list[RegressionCaseResult],
    candidates: list[CandidatePayload],
) -> float:
    has_replayed_ex2 = any(
        candidate.export_contract == "Ex-2" for candidate in candidates
    )
    if has_replayed_ex2:
        return compute_ex2_contract_completeness(candidates)
    if _results_expect_ex2(case_results):
        return 0.0
    return compute_ex2_contract_completeness(candidates)


def _unresolved_explicitness_from_replayed(
    case_results: list[RegressionCaseResult],
    candidates: list[CandidatePayload],
) -> float:
    entities = [
        entity
        for candidate in candidates
        for entity in _candidate_entities(candidate)
        if entity.resolution_status in {"unresolved", "ambiguous"}
    ]
    if not entities:
        return 0.0 if _results_expect_unresolved(case_results) else 1.0
    explicit = sum(1 for entity in entities if entity.canonical_id is None)
    return explicit / len(entities)


def _candidate_entities(candidate: CandidatePayload) -> list[Any]:
    if candidate.export_contract == "Ex-1":
        return list(candidate.involved_entities)
    if candidate.export_contract == "Ex-2":
        return list(candidate.affected_entities)
    return [candidate.subject_entity, candidate.object_entity]


def _results_expect_candidates(case_results: list[RegressionCaseResult]) -> bool:
    return any(result.expected_outputs for result in case_results)


def _results_expect_ex2(case_results: list[RegressionCaseResult]) -> bool:
    return any(
        output.export_contract == "Ex-2"
        for result in case_results
        for output in result.expected_outputs
    )


def _results_expect_unresolved(case_results: list[RegressionCaseResult]) -> bool:
    return any(
        entity.resolution_status in {"unresolved", "ambiguous"}
        for result in case_results
        for output in result.expected_outputs
        for entity in [
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
    )


def _threshold_violations(
    metrics: dict[str, float],
    thresholds: RegressionThresholds,
) -> list[str]:
    checks = [
        ("evidence_coverage", ">=", thresholds.evidence_coverage),
        ("dedupe_precision", ">=", thresholds.dedupe_precision),
        ("unresolved_explicitness", ">=", thresholds.unresolved_explicitness),
        ("ex2_contract_completeness", ">=", thresholds.ex2_contract_completeness),
        ("ex3_false_positive_rate", "<=", thresholds.ex3_false_positive_rate),
    ]
    violations: list[str] = []
    for name, operator, threshold in checks:
        value = metrics[name]
        if operator == ">=" and value < threshold:
            violations.append(f"{name} {value:.4f} below threshold {threshold:.4f}")
        if operator == "<=" and value > threshold:
            violations.append(f"{name} {value:.4f} above threshold {threshold:.4f}")
    return violations


__all__ = ["run_regression_suite"]
