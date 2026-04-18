"""Regression fixture suite runner."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from subsystem_news.contracts import NewsSourceConfig
from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import (
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.dedupe.cluster import DedupeDecision, merge_into_cluster_with_decision
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.entities.mention import detect_mentions
from subsystem_news.entities.resolution import (
    EntityResolutionResult,
    resolve_detected_mentions,
)
from subsystem_news.entities.resolver_client import (
    EntityRegistryClient,
    HttpEntityRegistryClient,
)
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.fact_extractor import extract_facts
from subsystem_news.extract.runtime_client import (
    DefaultReasonerRuntimeClient,
    ReasonerRuntimeClient,
)
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN, SchemaPin
from subsystem_news.graph import GRAPH_SCHEMA_PIN, extract_graph_deltas
from subsystem_news.fixtures.catalog import (
    FixtureArticleInput,
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
from subsystem_news.normalize.pipeline import normalize_article
from subsystem_news.runtime.models import CandidatePayload
from subsystem_news.runtime.replay import (
    ReplayArticleResult,
    ReplayArticleSummary,
    ReplayRequest,
    ReplayResult,
    ReplayRunResult,
    diff_replay_results,
    replay_article,
)
from subsystem_news.signals.aggregator import generate_signals
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN
from subsystem_news.sources.base import (
    NewsArticleRef,
    RawArticleFetch,
    raw_content_hash,
    trace_id_for,
)


def run_regression_suite(
    suite: FixtureSuite,
    *,
    thresholds: RegressionThresholds,
    replay_runner: Callable[[ReplayRequest], ReplayResult] | None = None,
) -> RegressionReport:
    """Run the checked-in fixture suite through the provided replay runner."""

    validate_fixture_suite(suite)
    active_replay_runner = replay_runner or fixture_replay_runner()
    case_results: list[RegressionCaseResult] = []
    all_candidates: list[CandidatePayload] = []

    for case in suite.cases:
        case_result, case_candidates = _run_case(case, suite, active_replay_runner)
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
    baseline_request = ReplayRequest(
        case_id=case.case_id,
        category=case.category,
        article_ids=list(case.article_ids),
        input_path=baseline_path,
        baseline_path=baseline_path,
        metadata={"expected_cluster_id": case.expected_cluster_id},
    )
    replay_request = ReplayRequest(
        case_id=case.case_id,
        category=case.category,
        article_ids=list(case.article_ids),
        input_path=_case_replay_input_path(case, suite),
        baseline_path=baseline_path,
        metadata={
            "expected_cluster_id": case.expected_cluster_id,
            "fixture_case": case.model_dump(mode="json"),
        },
    )
    try:
        baseline = replay_article(baseline_request)
        replayed = replay_runner(replay_request)
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


def fixture_replay_runner(
    *,
    entity_client: EntityRegistryClient | None = None,
    reasoner_client: ReasonerRuntimeClient | None = None,
    dedupe_threshold: float = 0.82,
) -> Callable[[ReplayRequest], ReplayResult]:
    """Build the default real fixture replay runner.

    Unlike ``replay_article()``, this runner does not load the baseline snapshot as
    replay output. It reconstructs replay inputs from the fixture case payload and
    executes normalize/dedupe/entities/extract/signals/graph with configured
    runtime clients.
    """

    active_entity_client = entity_client or _configured_entity_client()
    active_reasoner_client = reasoner_client or DefaultReasonerRuntimeClient()

    def _runner(request: ReplayRequest) -> ReplayResult:
        return replay_fixture_case(
            request,
            entity_client=active_entity_client,
            reasoner_client=active_reasoner_client,
            dedupe_threshold=dedupe_threshold,
        )

    return _runner


def replay_fixture_case(
    request: ReplayRequest,
    *,
    entity_client: EntityRegistryClient,
    reasoner_client: ReasonerRuntimeClient,
    dedupe_threshold: float = 0.82,
) -> ReplayResult:
    """Replay one fixture case from raw inputs or normalized artifacts."""

    if not 0.0 <= dedupe_threshold <= 1.0:
        raise ValueError("dedupe_threshold must be between 0 and 1")

    case = _fixture_case_from_request(request)
    schema_pins = _schema_pins_for_case(case)
    started_at = datetime.now(timezone.utc)
    stage_order: list[str] = ["load_fixture"]
    article_results: list[ReplayArticleResult] = []
    contexts: list[Any] = []

    artifacts, normalized_from_raw = _fixture_artifacts(case)
    if normalized_from_raw:
        stage_order.append("normalize")

    with tempfile.TemporaryDirectory(prefix="subsystem-news-fixture-replay-") as temp_root:
        dedupe_store = DedupeStore(Path(temp_root) / "dedupe")
        for artifact in artifacts:
            last_stage = "load_fixture"
            try:
                last_stage = "dedupe"
                stage_order.append("dedupe")
                dedupe_decision = merge_into_cluster_with_decision(
                    artifact,
                    dedupe_store,
                    threshold=dedupe_threshold,
                )
                cluster = dedupe_decision.cluster
                clustered_artifact = dedupe_store.load_article_snapshot(artifact.article_id)
                representative = dedupe_store.load_article_snapshot(
                    cluster.representative_article_id
                )

                last_stage = "mention_detect"
                stage_order.append("mention_detect")
                mentions = detect_mentions(representative)

                last_stage = "entity_resolve"
                stage_order.append("entity_resolve")
                entity_resolution = resolve_detected_mentions(
                    mentions,
                    entity_client,
                )

                last_stage = "extract"
                stage_order.append("extract")
                facts = extract_facts(
                    representative,
                    cluster,
                    entity_resolution,
                    reasoner_client,
                    schema_pin=schema_pins["Ex-1"],
                )

                last_stage = "signals"
                stage_order.append("signals")
                signals = generate_signals(
                    facts,
                    reasoner_client,
                    schema_pin=schema_pins["Ex-2"],
                )

                last_stage = "graph"
                stage_order.append("graph")
                graph_deltas = extract_graph_deltas(
                    representative,
                    cluster,
                    entity_resolution,
                    facts,
                    reasoner_client,
                    schema_pin=schema_pins["Ex-3"],
                )

                context = _FixtureReplayContext(
                    article_id=clustered_artifact.article_id,
                    cluster_id=cluster.cluster_id,
                    source_reference=clustered_artifact.source_reference,
                    artifact=clustered_artifact,
                    representative_artifact=representative,
                    entity_resolution=entity_resolution,
                    facts=facts,
                    signals=signals,
                    graph_deltas=graph_deltas,
                    schema_pins=schema_pins,
                    dedupe_metadata=_dedupe_metadata(
                        dedupe_decision,
                        threshold=dedupe_threshold,
                    ),
                )
                contexts.append(context)
                article_results.append(_article_result_for_context(context))
            except Exception as exc:  # noqa: BLE001 - replay reports per-article failures.
                article_results.append(
                    ReplayArticleResult(
                        article_id=artifact.article_id,
                        source_reference=artifact.source_reference,
                        status="failed",
                        baseline_available=False,
                        error_stage=last_stage,
                        error_message=f"{exc.__class__.__name__}: {exc}",
                    )
                )

    if stage_order[-1:] != ["diff"]:
        stage_order.append("diff")
    error_count = sum(1 for result in article_results if result.status == "failed")
    return ReplayRunResult(
        replay_id=_fixture_replay_id(started_at, request),
        input_kind="artifact",
        input_path=str(request.input_path),
        source_run_id=None,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        article_results=article_results,
        changed_count=0,
        error_count=error_count,
        has_changes=False,
        stage_order=stage_order,
        metadata={
            "case_id": case.case_id,
            "category": case.category,
            "article_count": len(artifacts),
            **_metadata_for_fixture_contexts(contexts),
        },
    )


class _FixtureReplayContext:
    def __init__(
        self,
        *,
        article_id: str,
        cluster_id: str,
        source_reference: Any,
        artifact: NewsArticleArtifact,
        representative_artifact: NewsArticleArtifact,
        entity_resolution: EntityResolutionResult,
        facts: list[NewsFactCandidate],
        signals: list[NewsSignalCandidate],
        graph_deltas: list[NewsGraphDeltaCandidate],
        schema_pins: dict[str, Any],
        dedupe_metadata: dict[str, Any],
    ) -> None:
        self.article_id = article_id
        self.cluster_id = cluster_id
        self.source_reference = source_reference
        self.artifact = artifact
        self.representative_artifact = representative_artifact
        self.entity_resolution = entity_resolution
        self.facts = facts
        self.signals = signals
        self.graph_deltas = graph_deltas
        self.schema_pins = schema_pins
        self.dedupe_metadata = dedupe_metadata


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


def _case_replay_input_path(case: FixtureCase, suite: FixtureSuite) -> Path:
    if suite.manifest_path is not None:
        return suite.manifest_path
    if suite.root_path is not None:
        return suite.root_path / "manifest.json"
    return Path(f"{case.case_id}.fixture.json")


def _fixture_case_from_request(request: ReplayRequest) -> FixtureCase:
    payload = request.metadata.get("fixture_case")
    if payload is None:
        raise ContractViolationError(
            "fixture replay requires fixture_case metadata; use run_regression_suite"
        )
    try:
        return FixtureCase.model_validate(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ContractViolationError("fixture_case metadata violates FixtureCase") from exc


def _schema_pins_for_case(case: FixtureCase) -> dict[str, SchemaPin]:
    required = {"Ex-1": FACT_SCHEMA_PIN, "Ex-2": SIGNAL_SCHEMA_PIN, "Ex-3": GRAPH_SCHEMA_PIN}
    missing = set(required) - set(case.version_pins)
    if missing:
        raise ContractViolationError(
            "fixture replay requires schema pins for "
            + ", ".join(sorted(missing))
        )
    pins = {contract: case.version_pins[contract] for contract in sorted(required)}
    for contract, expected in required.items():
        _require_fixture_schema_pin(contract, pins[contract], expected)
    return pins


def _require_fixture_schema_pin(
    contract: str,
    pin: SchemaPin,
    expected: SchemaPin,
) -> None:
    if pin.contract != contract:
        raise ContractViolationError(
            f"{contract} fixture schema pin has contract {pin.contract}"
        )
    for field_name in ("schema_name", "schema_version", "model_output_version"):
        if getattr(pin, field_name) != getattr(expected, field_name):
            raise ContractViolationError(
                f"{contract} fixture schema pin has unsupported {field_name}: "
                f"{getattr(pin, field_name)}"
            )


def _fixture_artifacts(
    case: FixtureCase,
) -> tuple[list[NewsArticleArtifact], bool]:
    raw_inputs = {raw_input.article_id: raw_input for raw_input in case.raw_inputs}
    artifact_hints = {
        artifact.article_id: artifact for artifact in case.normalized_artifacts
    }
    artifacts: list[NewsArticleArtifact] = []
    normalized_from_input = False
    for article_id in case.article_ids:
        raw_input = raw_inputs.get(article_id)
        if raw_input is not None:
            artifacts.append(_artifact_from_raw_input(raw_input, artifact_hints.get(article_id)))
            normalized_from_input = True
            continue

        artifact = artifact_hints.get(article_id)
        if artifact is not None:
            artifacts.append(_artifact_from_normalized_artifact(artifact))
            normalized_from_input = True
            continue

        raise ContractViolationError(
            f"{case.case_id} fixture replay has no raw_input or normalized_artifact "
            f"for article_id {article_id}"
        )

    return artifacts, normalized_from_input


def _artifact_from_raw_input(
    raw_input: FixtureArticleInput,
    artifact_hint: NewsArticleArtifact | None,
) -> NewsArticleArtifact:
    raw_fetch = _raw_fetch_from_fixture_input(raw_input, artifact_hint)
    normalized = normalize_article(raw_fetch)
    return normalized.model_copy(
        update={
            "article_id": raw_input.article_id,
            "cluster_id": None,
        }
    )


def _artifact_from_normalized_artifact(
    artifact: NewsArticleArtifact,
) -> NewsArticleArtifact:
    raw_fetch = _raw_fetch_from_artifact(artifact)
    normalized = normalize_article(raw_fetch)
    return normalized.model_copy(
        update={
            "article_id": artifact.article_id,
            "cluster_id": None,
        }
    )


def _raw_fetch_from_fixture_input(
    raw_input: FixtureArticleInput,
    artifact_hint: NewsArticleArtifact | None,
) -> RawArticleFetch:
    source_reference = raw_input.source_reference
    url = str(source_reference.url) if source_reference.url is not None else None
    source_id = source_reference.source_id
    source = NewsSourceConfig(
        source_id=source_id,
        display_name=source_id,
        access_mode="api",
        base_url=url or "https://fixture.invalid/",
        approved=True,
        reliability_tier=(
            artifact_hint.reliability_tier if artifact_hint is not None else "C"
        ),
        license_tag=artifact_hint.license_tag if artifact_hint is not None else "fixture",
        language=artifact_hint.language if artifact_hint is not None else "und",
        credential_ref=None,
    )
    ref = NewsArticleRef(
        source_id=source_id,
        source_reference=source_reference,
        url=url,
        provider_key=source_reference.provider_key,
        title_hint=raw_input.title,
        published_at_hint=raw_input.published_at,
        cursor=source_reference.provider_key or url,
    )
    payload = {
        "source_reference": source_reference,
        "raw_title": raw_input.title,
        "raw_body": raw_input.body_text,
        "published_at_raw": raw_input.published_at.isoformat(),
        "author_or_channel": (
            artifact_hint.author_or_channel
            if artifact_hint is not None
            else "Fixture"
        ),
    }
    content_hash = raw_content_hash(payload)
    return RawArticleFetch(
        ref=ref,
        source=source,
        raw_title=raw_input.title,
        raw_body=raw_input.body_text,
        raw_html=None,
        summary=None,
        published_at_raw=raw_input.published_at.isoformat(),
        author_or_channel=str(payload["author_or_channel"]),
        fetched_at=raw_input.fetched_at,
        content_hash=content_hash,
        trace_id=trace_id_for(source_id, content_hash, raw_input.fetched_at),
    )


def _raw_fetch_from_artifact(artifact: NewsArticleArtifact) -> RawArticleFetch:
    source_reference = artifact.source_reference
    url = str(source_reference.url) if source_reference.url is not None else None
    source = NewsSourceConfig(
        source_id=artifact.source_id,
        display_name=artifact.source_id,
        access_mode="api",
        base_url=url or "https://fixture.invalid/",
        approved=True,
        reliability_tier=artifact.reliability_tier,
        license_tag=artifact.license_tag,
        language=artifact.language,
        credential_ref=None,
    )
    ref = NewsArticleRef(
        source_id=artifact.source_id,
        source_reference=source_reference,
        url=url,
        provider_key=source_reference.provider_key,
        title_hint=artifact.title,
        published_at_hint=artifact.published_at,
        cursor=source_reference.provider_key or url,
    )
    payload = {
        "source_reference": source_reference,
        "raw_title": artifact.title,
        "raw_body": artifact.body_text,
        "published_at_raw": artifact.published_at.isoformat(),
        "author_or_channel": artifact.author_or_channel,
    }
    content_hash = raw_content_hash(payload)
    return RawArticleFetch(
        ref=ref,
        source=source,
        raw_title=artifact.title,
        raw_body=artifact.body_text,
        raw_html=None,
        summary=None,
        published_at_raw=artifact.published_at.isoformat(),
        author_or_channel=artifact.author_or_channel,
        fetched_at=artifact.fetched_at,
        content_hash=content_hash,
        trace_id=trace_id_for(artifact.source_id, content_hash, artifact.fetched_at),
    )


def _article_result_for_context(context: _FixtureReplayContext) -> ReplayArticleResult:
    return ReplayArticleResult(
        article_id=context.article_id,
        source_reference=context.source_reference,
        status="processed",
        baseline_available=False,
        has_changes=False,
        replayed=ReplayArticleSummary(
            article_id=context.article_id,
            cluster_id=context.cluster_id,
            representative_article_id=context.representative_artifact.article_id,
            source_reference=context.source_reference,
            candidate_ids=[
                _candidate_key(candidate) for candidate in _context_candidates(context)
            ],
            schema_pins=_version_map(context),
        ),
    )


def _metadata_for_fixture_contexts(
    contexts: list[_FixtureReplayContext],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    evidence_spans: dict[str, Any] = {}
    entity_resolutions: dict[str, Any] = {}
    schema_pins: dict[str, Any] = {}
    dedupe_decisions: dict[str, Any] = {}

    for context in contexts:
        dedupe_decisions[context.article_id] = context.dedupe_metadata
        for candidate in _context_candidates(context):
            candidates.append(candidate.model_dump(mode="json"))
            for index, span in enumerate(candidate.evidence_spans):
                evidence_spans[f"{_candidate_key(candidate)}:evidence:{index}"] = (
                    span.model_dump(mode="json")
                )
            for entity in _candidate_entities(candidate):
                entity_resolutions[f"{candidate.candidate_id}:{entity.mention_text}"] = (
                    entity.model_dump(mode="json")
                )
        for name, pin in _version_map(context).items():
            schema_pins.setdefault(name, pin)

    return {
        "candidate_payloads": candidates,
        "evidence_spans": evidence_spans,
        "entity_resolutions": entity_resolutions,
        "schema_pins": schema_pins,
        "dedupe_decisions": dedupe_decisions,
    }


def _context_candidates(context: _FixtureReplayContext) -> list[CandidatePayload]:
    return [*context.facts, *context.signals, *context.graph_deltas]


def _candidate_key(candidate: CandidatePayload) -> str:
    return f"{candidate.export_contract}:{candidate.candidate_id}"


def _version_map(context: _FixtureReplayContext) -> dict[str, dict[str, Any]]:
    return {
        name: pin.model_dump(mode="json")
        for name, pin in sorted(context.schema_pins.items())
    }


def _dedupe_metadata(
    decision: DedupeDecision,
    *,
    threshold: float,
) -> dict[str, Any]:
    cluster = decision.cluster
    return {
        "threshold": threshold,
        "cluster_id": cluster.cluster_id,
        "representative_article_id": cluster.representative_article_id,
        "member_count": len(cluster.member_article_ids),
        "cluster_confidence": cluster.cluster_confidence,
        "created": decision.created,
        "match_reason": None if decision.match is None else decision.match.reason,
        "match_confidence": None if decision.match is None else decision.match.score,
        "matched_article_ids": []
        if decision.match is None
        else list(decision.match.matched_article_ids),
        "conflict_count": len(decision.conflicts),
        "conflicts": [conflict.model_dump(mode="json") for conflict in decision.conflicts],
    }


def _configured_entity_client() -> EntityRegistryClient:
    base_url = (
        os.environ.get("SUBSYSTEM_NEWS_ENTITY_REGISTRY_URL")
        or os.environ.get("ENTITY_REGISTRY_URL")
        or ""
    ).strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ContractViolationError(
            "fixture replay requires an entity-registry URL in "
            "SUBSYSTEM_NEWS_ENTITY_REGISTRY_URL or ENTITY_REGISTRY_URL, "
            "or an explicit entity_client"
        )
    return HttpEntityRegistryClient(base_url)


def _fixture_replay_id(started_at: datetime, request: ReplayRequest) -> str:
    stamp = started_at.strftime("%Y%m%dT%H%M%S%fZ")
    return f"fixture-replay-{request.case_id}-{stamp}"


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


__all__ = [
    "fixture_replay_runner",
    "replay_fixture_case",
    "run_regression_suite",
]
