"""Runtime replay and structured comparison helpers."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from subsystem_news.contracts import NewsSourceConfig
from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.dedupe.cluster import merge_into_cluster
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.entities.mention import Mention, detect_mentions
from subsystem_news.entities.resolution import EntityResolutionResult, resolve_detected_mentions
from subsystem_news.entities.resolver_client import EntityRegistryClient
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.fact_extractor import extract_facts
from subsystem_news.extract.runtime_client import ReasonerRuntimeClient
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN, SchemaPin
from subsystem_news.graph import GRAPH_SCHEMA_PIN, extract_graph_deltas
from subsystem_news.normalize.pipeline import normalize_article
from subsystem_news.runtime.models import (
    CandidatePayload,
    PipelineArticleContext,
)
from subsystem_news.runtime.trace import load_pipeline_trace
from subsystem_news.signals.aggregator import generate_signals
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN
from subsystem_news.sources.base import (
    NewsArticleRef,
    RawArticleFetch,
    raw_content_hash,
    trace_id_for,
)


class ReplayValueDiff(BaseModel):
    """One comparable value-level difference found during replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    change: Literal["added", "removed", "changed"]
    before: Any | None = None
    after: Any | None = None


class ReplayArticleSummary(BaseModel):
    """Compact replay output identity for one article context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str
    cluster_id: str
    representative_article_id: str
    source_reference: SourceReference
    candidate_ids: list[str] = Field(default_factory=list)
    schema_pins: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ReplayArticleResult(BaseModel):
    """Replay comparison for one trace article."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str | None = None
    source_reference: SourceReference | None = None
    status: Literal["processed", "failed"]
    baseline_available: bool
    has_changes: bool = False
    baseline: ReplayArticleSummary | None = None
    replayed: ReplayArticleSummary | None = None
    candidate_diffs: list[ReplayValueDiff] = Field(default_factory=list)
    evidence_span_diffs: list[ReplayValueDiff] = Field(default_factory=list)
    entity_resolution_diffs: list[ReplayValueDiff] = Field(default_factory=list)
    version_metadata_diffs: list[ReplayValueDiff] = Field(default_factory=list)
    error_stage: str | None = None
    error_message: str | None = None


class ReplayRunResult(BaseModel):
    """Structured replay result suitable for regression review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    replay_id: str
    input_kind: Literal["trace", "artifact"]
    input_path: str
    source_run_id: str | None = None
    started_at: datetime
    completed_at: datetime
    article_results: list[ReplayArticleResult] = Field(default_factory=list)
    changed_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    has_changes: bool = False
    stage_order: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReplayRequest(BaseModel):
    """Single fixture replay request.

    The full runtime replay path is trace/artifact based. Regression fixtures use the
    same result shape but pass a checked-in snapshot path through this lightweight
    request object so callers can inject the real replay runner when available.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    category: str
    article_ids: list[str] = Field(default_factory=list)
    input_path: Path
    baseline_path: Path | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


ReplayResult = ReplayRunResult


class ReplayDiff(BaseModel):
    """Aggregated difference between two replay snapshots."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    has_changes: bool = False
    changed_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    candidate_diffs: list[ReplayValueDiff] = Field(default_factory=list)
    evidence_span_diffs: list[ReplayValueDiff] = Field(default_factory=list)
    entity_resolution_diffs: list[ReplayValueDiff] = Field(default_factory=list)
    schema_pin_diffs: list[ReplayValueDiff] = Field(default_factory=list)
    article_diffs: list[ReplayArticleResult] = Field(default_factory=list)


def replay_article(request: ReplayRequest) -> ReplayResult:
    """Load the replay snapshot referenced by a fixture request.

    Production callers can pass a custom runner to the fixture regression layer. This
    default intentionally avoids reconstructing the business pipeline in fixtures.
    """

    return _load_replay_result(request.input_path)


def diff_replay_results(
    baseline: ReplayResult,
    replayed: ReplayResult,
) -> ReplayDiff:
    """Compare two replay snapshots using the existing stable diff primitive."""

    candidate_diffs = _diff_maps(
        _result_candidate_summary_map(baseline),
        _result_candidate_summary_map(replayed),
    )
    evidence_span_diffs = _diff_maps(
        _result_metadata_map(baseline, "evidence_spans"),
        _result_metadata_map(replayed, "evidence_spans"),
    )
    entity_resolution_diffs = _diff_maps(
        _result_metadata_map(baseline, "entity_resolutions"),
        _result_metadata_map(replayed, "entity_resolutions"),
    )
    schema_pin_diffs = _diff_maps(
        _result_schema_pin_map(baseline),
        _result_schema_pin_map(replayed),
    )

    changed_articles = [
        article
        for article in replayed.article_results
        if article.has_changes
        or article.candidate_diffs
        or article.evidence_span_diffs
        or article.entity_resolution_diffs
        or article.version_metadata_diffs
    ]
    if not changed_articles:
        changed_articles = [
            article
            for article in replayed.article_results
            if article.status == "failed"
        ]

    changed_count = (
        len(candidate_diffs)
        + len(evidence_span_diffs)
        + len(entity_resolution_diffs)
        + len(schema_pin_diffs)
        + replayed.changed_count
    )
    has_changes = any(
        (
            candidate_diffs,
            evidence_span_diffs,
            entity_resolution_diffs,
            schema_pin_diffs,
            replayed.has_changes,
            replayed.error_count,
        )
    )
    return ReplayDiff(
        has_changes=has_changes,
        changed_count=changed_count,
        error_count=replayed.error_count,
        candidate_diffs=candidate_diffs,
        evidence_span_diffs=evidence_span_diffs,
        entity_resolution_diffs=entity_resolution_diffs,
        schema_pin_diffs=schema_pin_diffs,
        article_diffs=changed_articles,
    )


def replay_trace(
    trace_path: Path,
    *,
    entity_client: EntityRegistryClient,
    reasoner_client: ReasonerRuntimeClient,
    dedupe_threshold: float | None = None,
) -> ReplayRunResult:
    """Load a prior pipeline trace, rerun processing, and emit comparable diffs."""

    stage_order = ["load_trace"]
    trace = load_pipeline_trace(trace_path)
    contexts = [
        article.context
        for article in trace.article_results
        if article.context is not None
    ]
    return _replay_contexts(
        contexts,
        input_kind="trace",
        input_path=trace_path,
        source_run_id=trace.run_id,
        stage_order=stage_order,
        entity_client=entity_client,
        reasoner_client=reasoner_client,
        dedupe_threshold=dedupe_threshold,
    )


def replay_artifact_snapshot(
    artifact_path: Path,
    *,
    entity_client: EntityRegistryClient,
    reasoner_client: ReasonerRuntimeClient,
    schema_pins: Mapping[str, SchemaPin] | None = None,
    dedupe_threshold: float = 0.82,
) -> ReplayRunResult:
    """Replay a normalized article artifact snapshot without a baseline diff."""

    stage_order = ["load_artifact"]
    artifact = _load_artifact_snapshot(artifact_path)
    pins = dict(
        schema_pins
        or {"Ex-1": FACT_SCHEMA_PIN, "Ex-2": SIGNAL_SCHEMA_PIN, "Ex-3": GRAPH_SCHEMA_PIN}
    )
    baseline = PipelineArticleContext(
        article_id=artifact.article_id,
        cluster_id="artifact-snapshot-baseline",
        source_reference=artifact.source_reference,
        artifact=artifact,
        representative_artifact=artifact,
        cluster=_single_artifact_placeholder_cluster(artifact),
        entity_resolution=EntityResolutionResult(
            mentions=[],
            resolved_mentions=[],
            entities=[],
        ),
        facts=[],
        signals=[],
        schema_pins=pins,
    )
    return _replay_contexts(
        [baseline],
        input_kind="artifact",
        input_path=artifact_path,
        source_run_id=None,
        stage_order=stage_order,
        entity_client=entity_client,
        reasoner_client=reasoner_client,
        dedupe_threshold=dedupe_threshold,
        compare_to_baseline=False,
    )


def _replay_contexts(
    contexts: list[PipelineArticleContext],
    *,
    input_kind: Literal["trace", "artifact"],
    input_path: Path,
    source_run_id: str | None,
    stage_order: list[str],
    entity_client: EntityRegistryClient,
    reasoner_client: ReasonerRuntimeClient,
    dedupe_threshold: float | None,
    compare_to_baseline: bool = True,
) -> ReplayRunResult:
    started_at = datetime.now(timezone.utc)
    replay_id = _replay_id(started_at, input_path)
    article_results: list[ReplayArticleResult] = []
    replayed_contexts: list[PipelineArticleContext] = []

    with tempfile.TemporaryDirectory(prefix="subsystem-news-replay-") as temp_root:
        dedupe_store = DedupeStore(Path(temp_root) / "dedupe")
        for context in contexts:
            try:
                replayed = _replay_article_context(
                    context,
                    dedupe_store=dedupe_store,
                    entity_client=entity_client,
                    reasoner_client=reasoner_client,
                    dedupe_threshold=(
                        dedupe_threshold
                        if dedupe_threshold is not None
                        else float(context.dedupe_metadata.get("threshold", 0.82))
                    ),
                    stage_order=stage_order,
                )
                article_results.append(
                    _compare_contexts(
                        context if compare_to_baseline else None,
                        replayed,
                        source_reference=context.source_reference,
                    )
                )
                replayed_contexts.append(replayed)
            except Exception as exc:  # noqa: BLE001 - replay must report per-article drift.
                article_results.append(
                    ReplayArticleResult(
                        article_id=context.article_id,
                        source_reference=context.source_reference,
                        status="failed",
                        baseline_available=compare_to_baseline,
                        error_stage=stage_order[-1] if stage_order else "replay",
                        error_message=f"{exc.__class__.__name__}: {exc}",
                    )
                )

    if stage_order[-1:] != ["diff"]:
        stage_order.append("diff")
    changed_count = sum(
        1
        for result in article_results
        if result.baseline_available and result.has_changes
    )
    error_count = sum(1 for result in article_results if result.status == "failed")
    return ReplayRunResult(
        replay_id=replay_id,
        input_kind=input_kind,
        input_path=str(input_path),
        source_run_id=source_run_id,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        article_results=article_results,
        changed_count=changed_count,
        error_count=error_count,
        has_changes=changed_count > 0,
        stage_order=list(stage_order),
        metadata={
            "article_count": len(contexts),
            **_metadata_for_replayed_contexts(replayed_contexts),
        },
    )


def _replay_article_context(
    context: PipelineArticleContext,
    *,
    dedupe_store: DedupeStore,
    entity_client: EntityRegistryClient,
    reasoner_client: ReasonerRuntimeClient,
    dedupe_threshold: float,
    stage_order: list[str],
) -> PipelineArticleContext:
    schema_pins = _schema_pins_for_replay(context.schema_pins)

    stage_order.append("normalize")
    artifact = _renormalize_artifact(context.artifact)

    stage_order.append("dedupe")
    cluster = merge_into_cluster(
        artifact,
        dedupe_store,
        threshold=dedupe_threshold,
    )
    clustered_artifact = dedupe_store.load_article_snapshot(artifact.article_id)
    representative = dedupe_store.load_article_snapshot(cluster.representative_article_id)

    stage_order.append("mention_detect")
    mentions = detect_mentions(representative)

    stage_order.append("entity_resolve")
    entity_resolution = resolve_detected_mentions(mentions, entity_client)

    stage_order.append("extract")
    facts = extract_facts(
        representative,
        cluster,
        entity_resolution,
        reasoner_client,
        schema_pin=schema_pins["Ex-1"],
    )

    stage_order.append("signals")
    signals = generate_signals(
        facts,
        reasoner_client,
        schema_pin=schema_pins["Ex-2"],
    )

    stage_order.append("graph")
    graph_deltas = extract_graph_deltas(
        representative,
        cluster,
        entity_resolution,
        facts,
        reasoner_client,
        schema_pin=schema_pins["Ex-3"],
    )

    return PipelineArticleContext(
        article_id=clustered_artifact.article_id,
        cluster_id=cluster.cluster_id,
        source_reference=clustered_artifact.source_reference,
        artifact=clustered_artifact,
        representative_artifact=representative,
        cluster=cluster,
        entity_resolution=entity_resolution,
        facts=facts,
        signals=signals,
        graph_deltas=graph_deltas,
        schema_pins=schema_pins,
        dedupe_metadata={
            "threshold": dedupe_threshold,
            "cluster_id": cluster.cluster_id,
            "representative_article_id": cluster.representative_article_id,
            "member_count": len(cluster.member_article_ids),
            "cluster_confidence": cluster.cluster_confidence,
        },
        entity_metadata={
            "mention_count": len(entity_resolution.mentions),
            "resolved_count": sum(
                1
                for resolved in entity_resolution.resolved_mentions
                if resolved.entity.resolution_status == "resolved"
            ),
            "unresolved_count": sum(
                1
                for resolved in entity_resolution.resolved_mentions
                if resolved.entity.resolution_status == "unresolved"
            ),
        },
        extract_metadata={
            "fact_count": len(facts),
            "representative_article_id": representative.article_id,
        },
        signal_metadata={"signal_count": len(signals)},
        graph_metadata={"graph_delta_count": len(graph_deltas)},
    )


def _compare_contexts(
    baseline: PipelineArticleContext | None,
    replayed: PipelineArticleContext,
    *,
    source_reference: SourceReference,
) -> ReplayArticleResult:
    if baseline is None:
        return ReplayArticleResult(
            article_id=replayed.article_id,
            source_reference=source_reference,
            status="processed",
            baseline_available=False,
            has_changes=False,
            replayed=_summary_for_context(replayed),
        )

    candidate_diffs = _diff_maps(_candidate_map(baseline), _candidate_map(replayed))
    evidence_span_diffs = _diff_maps(_evidence_map(baseline), _evidence_map(replayed))
    entity_resolution_diffs = _diff_maps(
        _entity_resolution_map(baseline.entity_resolution),
        _entity_resolution_map(replayed.entity_resolution),
    )
    version_metadata_diffs = _diff_maps(_version_map(baseline), _version_map(replayed))
    has_changes = any(
        (
            candidate_diffs,
            evidence_span_diffs,
            entity_resolution_diffs,
            version_metadata_diffs,
        )
    )
    return ReplayArticleResult(
        article_id=baseline.article_id,
        source_reference=source_reference,
        status="processed",
        baseline_available=True,
        has_changes=has_changes,
        baseline=_summary_for_context(baseline),
        replayed=_summary_for_context(replayed),
        candidate_diffs=candidate_diffs,
        evidence_span_diffs=evidence_span_diffs,
        entity_resolution_diffs=entity_resolution_diffs,
        version_metadata_diffs=version_metadata_diffs,
    )


def _renormalize_artifact(artifact: NewsArticleArtifact) -> NewsArticleArtifact:
    raw = _raw_fetch_from_artifact(artifact)
    normalized = normalize_article(raw)
    if normalized.article_id != artifact.article_id:
        raise ContractViolationError("replay normalization changed article_id")
    return normalized


def _raw_fetch_from_artifact(artifact: NewsArticleArtifact) -> RawArticleFetch:
    source_reference = artifact.source_reference
    url = str(source_reference.url) if source_reference.url is not None else None
    ref = NewsArticleRef(
        source_id=artifact.source_id,
        source_reference=source_reference,
        url=url,
        provider_key=source_reference.provider_key,
        title_hint=artifact.title,
        published_at_hint=artifact.published_at,
        cursor=source_reference.provider_key or url,
    )
    source = NewsSourceConfig(
        source_id=artifact.source_id,
        display_name=artifact.source_id,
        access_mode="api",
        base_url=url or "https://replay.invalid/",
        approved=True,
        reliability_tier=artifact.reliability_tier,
        license_tag=artifact.license_tag,
        language=artifact.language,
        credential_ref=None,
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


def _schema_pins_for_replay(pins: Mapping[str, SchemaPin]) -> dict[str, SchemaPin]:
    replay_pins = dict(pins)
    replay_pins.setdefault("Ex-1", FACT_SCHEMA_PIN)
    replay_pins.setdefault("Ex-2", SIGNAL_SCHEMA_PIN)
    replay_pins.setdefault("Ex-3", GRAPH_SCHEMA_PIN)
    _require_schema_pin("Ex-1", replay_pins["Ex-1"])
    _require_schema_pin("Ex-2", replay_pins["Ex-2"])
    _require_schema_pin("Ex-3", replay_pins["Ex-3"])
    return replay_pins


def _require_schema_pin(contract: Literal["Ex-1", "Ex-2", "Ex-3"], pin: SchemaPin) -> None:
    if pin.contract != contract:
        raise ContractViolationError(f"{contract} replay schema pin has contract {pin.contract}")


def _summary_for_context(context: PipelineArticleContext) -> ReplayArticleSummary:
    candidates = _context_candidates(context)
    return ReplayArticleSummary(
        article_id=context.article_id,
        cluster_id=context.cluster_id,
        representative_article_id=context.representative_artifact.article_id,
        source_reference=context.source_reference,
        candidate_ids=[_candidate_key(candidate) for candidate in candidates],
        schema_pins=_version_map(context),
    )


def _candidate_map(context: PipelineArticleContext) -> dict[str, Any]:
    return {
        _candidate_key(candidate): candidate.model_dump(mode="json")
        for candidate in _context_candidates(context)
    }


def _evidence_map(context: PipelineArticleContext) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for candidate in _context_candidates(context):
        for index, span in enumerate(candidate.evidence_spans):
            evidence[
                f"{_candidate_key(candidate)}:evidence:{index}"
            ] = span.model_dump(mode="json")
    return evidence


def _entity_resolution_map(entity_resolution: EntityResolutionResult) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for mention in entity_resolution.mentions:
        payload[f"mention:{_mention_key(mention)}"] = mention.model_dump(mode="json")
    for resolved in entity_resolution.resolved_mentions:
        payload[f"resolved:{_mention_key(resolved.mention)}"] = {
            "entity": resolved.entity.model_dump(mode="json"),
            "resolution_source": resolved.resolution_source,
            "registry_resolution": (
                None
                if resolved.registry_resolution is None
                else resolved.registry_resolution.model_dump(mode="json")
            ),
        }
    for entity in entity_resolution.entities:
        key = "|".join(
            (
                entity.resolution_status,
                entity.canonical_id or "",
                entity.mention_text,
                entity.type_hint,
            )
        )
        payload[f"entity:{key}"] = entity.model_dump(mode="json")
    return payload


def _version_map(context: PipelineArticleContext) -> dict[str, dict[str, Any]]:
    return {
        name: pin.model_dump(mode="json")
        for name, pin in sorted(context.schema_pins.items())
    }


def _context_candidates(context: PipelineArticleContext) -> list[CandidatePayload]:
    return [*context.facts, *context.signals, *context.graph_deltas]


def _metadata_for_replayed_contexts(
    contexts: list[PipelineArticleContext],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    evidence_spans: dict[str, Any] = {}
    entity_resolutions: dict[str, Any] = {}
    schema_pins: dict[str, Any] = {}

    for context in contexts:
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
    }


def _candidate_entities(candidate: CandidatePayload) -> list[Any]:
    if candidate.export_contract == "Ex-1":
        return list(candidate.involved_entities)
    if candidate.export_contract == "Ex-2":
        return list(candidate.affected_entities)
    return [candidate.subject_entity, candidate.object_entity]


def _candidate_key(candidate: CandidatePayload) -> str:
    return f"{candidate.export_contract}:{candidate.candidate_id}"


def _mention_key(mention: Mention) -> str:
    return "|".join(
        (
            mention.article_id,
            mention.locator,
            str(mention.start_char),
            str(mention.end_char),
            mention.text,
            mention.type_hint,
        )
    )


_MISSING = object()


def _diff_maps(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[ReplayValueDiff]:
    diffs: list[ReplayValueDiff] = []
    for key in sorted(set(before) | set(after)):
        before_value = before.get(key, _MISSING)
        after_value = after.get(key, _MISSING)
        if before_value is _MISSING:
            diffs.append(ReplayValueDiff(key=key, change="added", after=after_value))
        elif after_value is _MISSING:
            diffs.append(ReplayValueDiff(key=key, change="removed", before=before_value))
        elif _stable_json(before_value) != _stable_json(after_value):
            diffs.append(
                ReplayValueDiff(
                    key=key,
                    change="changed",
                    before=before_value,
                    after=after_value,
                )
            )
    return diffs


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _load_replay_result(path: Path) -> ReplayResult:
    try:
        return ReplayRunResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractViolationError("replay snapshot violates ReplayRunResult") from exc


def _result_candidate_summary_map(result: ReplayResult) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for article in result.article_results:
        summary = article.replayed or article.baseline
        if summary is None:
            key = article.article_id or "unknown"
            payload[key] = {"status": article.status, "error_message": article.error_message}
            continue
        payload[summary.article_id] = {
            "cluster_id": summary.cluster_id,
            "representative_article_id": summary.representative_article_id,
            "source_reference": summary.source_reference.model_dump(mode="json"),
            "candidate_ids": summary.candidate_ids,
        }
    if "candidate_payloads" in result.metadata:
        payload["metadata:candidate_payloads"] = result.metadata["candidate_payloads"]
    return payload


def _result_metadata_map(result: ReplayResult, key: str) -> dict[str, Any]:
    value = result.metadata.get(key, {})
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, list):
        return {f"{key}:{index}": item for index, item in enumerate(value)}
    return {key: value}


def _result_schema_pin_map(result: ReplayResult) -> dict[str, Any]:
    pins: dict[str, Any] = {}
    for article in result.article_results:
        summary = article.replayed or article.baseline
        if summary is not None:
            pins[f"article:{summary.article_id}"] = summary.schema_pins
    metadata_pins = result.metadata.get("schema_pins")
    if isinstance(metadata_pins, Mapping):
        pins["metadata:schema_pins"] = dict(metadata_pins)
    return pins


def _load_artifact_snapshot(path: Path) -> NewsArticleArtifact:
    try:
        return NewsArticleArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ContractViolationError("article snapshot violates NewsArticleArtifact") from exc


def _single_artifact_placeholder_cluster(
    artifact: NewsArticleArtifact,
) -> NewsDedupeCluster:
    return NewsDedupeCluster(
        cluster_id="artifact-snapshot-baseline",
        representative_article_id=artifact.article_id,
        member_article_ids=[artifact.article_id],
        canonical_headline=artifact.title,
        first_published_at=artifact.published_at,
        source_count=1,
        fingerprint_family=artifact.article_fingerprint,
        cluster_confidence=1.0,
    )


def _replay_id(started_at: datetime, input_path: Path) -> str:
    seed = f"{started_at.isoformat()}\n{input_path}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    stamp = started_at.strftime("%Y%m%dT%H%M%S%fZ")
    return f"replay-{stamp}-{digest}"


__all__ = [
    "ReplayArticleResult",
    "ReplayArticleSummary",
    "ReplayDiff",
    "ReplayRequest",
    "ReplayResult",
    "ReplayRunResult",
    "ReplayValueDiff",
    "diff_replay_results",
    "replay_article",
    "replay_artifact_snapshot",
    "replay_trace",
]
