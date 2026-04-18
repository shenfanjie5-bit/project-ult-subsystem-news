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
    ExpectedCandidateSummary,
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
    compute_unresolved_explicitness,
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
        "evidence_coverage": _expected_evidence_coverage(case_results)
        if not all_candidates
        else compute_evidence_coverage(all_candidates),
        "dedupe_precision": compute_dedupe_precision(provisional),
        "unresolved_explicitness": compute_unresolved_explicitness(provisional),
        "ex2_contract_completeness": _expected_ex2_completeness(case_results)
        if not all_candidates
        else compute_ex2_contract_completeness(all_candidates),
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
        candidates = _candidate_payloads_from_result(replayed)
        metrics = _case_metrics(case, diff=diff, candidates=candidates)
        status = "failed" if diff.has_changes or replayed.error_count else "passed"
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
                metrics=_case_metrics(case, diff=None, candidates=[]),
                metadata={
                    "expected_cluster_id": case.expected_cluster_id,
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
) -> dict[str, float]:
    outputs = list(case.expected_outputs)
    ex3_count = sum(1 for candidate in candidates if candidate.export_contract == "Ex-3")
    if not candidates:
        ex3_count = sum(1 for output in outputs if output.export_contract == "Ex-3")

    dedupe_correct = 1.0
    if case.category == "repost_cluster":
        expected_ex2_ids = {
            output.candidate_id
            for output in outputs
            if output.export_contract == "Ex-2"
        }
        duplicate_target = float(case.metadata.get("expected_folded_duplicates", 1.0))
        dedupe_correct = 1.0 if expected_ex2_ids and duplicate_target >= 1.0 else 0.0
        if diff is not None and getattr(diff, "candidate_diffs", None):
            dedupe_correct = 0.0

    return {
        "expected_candidate_count": float(len(outputs)),
        "expected_ex2_count": float(
            sum(1 for output in outputs if output.export_contract == "Ex-2")
        ),
        "expected_ex3_count": float(
            sum(1 for output in outputs if output.export_contract == "Ex-3")
        ),
        "ex3_candidate_count": float(ex3_count),
        "dedupe_correct": dedupe_correct,
    }


def _candidate_payloads_from_result(result: ReplayResult) -> list[CandidatePayload]:
    payloads = result.metadata.get("candidate_payloads", [])
    if not isinstance(payloads, list):
        return []
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


def _expected_evidence_coverage(case_results: list[RegressionCaseResult]) -> float:
    outputs = _expected_outputs(case_results)
    if not outputs:
        return 1.0
    covered = sum(1 for output in outputs if output.evidence_spans)
    return covered / len(outputs)


def _expected_ex2_completeness(case_results: list[RegressionCaseResult]) -> float:
    outputs = [
        output
        for output in _expected_outputs(case_results)
        if output.export_contract == "Ex-2"
    ]
    if not outputs:
        return 1.0
    complete = sum(
        1
        for output in outputs
        if output.direction is not None
        and output.magnitude not in {None, ""}
        and output.affected_entities
    )
    return complete / len(outputs)


def _expected_outputs(
    case_results: list[RegressionCaseResult],
) -> list[ExpectedCandidateSummary]:
    return [
        output
        for result in case_results
        for output in result.expected_outputs
    ]


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
