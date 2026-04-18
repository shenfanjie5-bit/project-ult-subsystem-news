"""Runtime pipeline assembly for approved news ingestion."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

from subsystem_news.contracts import NewsSourceConfig
from subsystem_news.dedupe.cluster import merge_into_cluster
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.entities.mention import detect_mentions
from subsystem_news.entities.resolution import resolve_detected_mentions
from subsystem_news.entities.resolver_client import EntityRegistryClient
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.fact_extractor import extract_facts
from subsystem_news.extract.runtime_client import ReasonerRuntimeClient
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN
from subsystem_news.normalize.pipeline import normalize_article
from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.runtime.models import (
    CandidatePayload,
    PipelineArticleContext,
    PipelineArticleResult,
    PipelineRunResult,
)
from subsystem_news.runtime.submit import (
    SubsystemSdkClient,
    submit_candidates,
    validate_candidate_batch,
)
from subsystem_news.runtime.trace import (
    candidate_idempotency_key,
    load_pipeline_trace,
    write_pipeline_trace,
)
from subsystem_news.signals.aggregator import generate_signals
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN
from subsystem_news.sources.base import HttpTransport
from subsystem_news.sources.discover import discover_articles, fetch_article_body
from subsystem_news.sources.registry import AdapterRegistry


class Pipeline:
    """Coordinate source, normalize, dedupe, entity, extract, signal, and submit."""

    def __init__(
        self,
        *,
        configs: Sequence[NewsSourceConfig],
        artifact_store: ArtifactStore,
        dedupe_store: DedupeStore,
        entity_client: EntityRegistryClient,
        reasoner_client: ReasonerRuntimeClient,
        sdk_client: SubsystemSdkClient,
        trace_dir: Path,
        submit_batch_size: int = 100,
        dedupe_threshold: float = 0.82,
        dry_run: bool = False,
        source_registry: AdapterRegistry | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        if submit_batch_size < 1:
            raise ValueError("submit_batch_size must be at least 1")
        if not 0.0 <= dedupe_threshold <= 1.0:
            raise ValueError("dedupe_threshold must be between 0 and 1")

        self.configs = list(configs)
        self.artifact_store = artifact_store
        self.dedupe_store = dedupe_store
        self.entity_client = entity_client
        self.reasoner_client = reasoner_client
        self.sdk_client = sdk_client
        self.trace_dir = trace_dir
        self.submit_batch_size = submit_batch_size
        self.dedupe_threshold = dedupe_threshold
        self.dry_run = dry_run
        self.source_registry = source_registry
        self.transport = transport

    def run(self, source_cursor: Mapping[str, str] | None = None) -> PipelineRunResult:
        """Run one fixed-order ingest pass over the approved source configs."""

        started_at = datetime.now(timezone.utc)
        run_id = _run_id(started_at)
        stage_order: list[str] = []
        article_results: list[PipelineArticleResult] = []
        submit_receipts: list[dict[str, object]] = []
        discovered_count = 0
        fetched_count = 0
        top_level_error: str | None = None

        try:
            stage_order.append("discover")
            refs = discover_articles(
                self.configs,
                cursor=source_cursor,
                registry=self.source_registry,
                transport=self.transport,
            )
            discovered_count = len(refs)
        except Exception as exc:  # noqa: BLE001 - traces must capture boundary failures.
            top_level_error = _error_message(exc)
            result = self._build_result(
                run_id=run_id,
                started_at=started_at,
                discovered_count=0,
                fetched_count=0,
                article_results=[],
                submit_receipts=[],
                stage_order=stage_order,
                top_level_error=top_level_error,
            )
            return self._write_trace(result, stage_order)

        for ref in refs:
            error_stage = "fetch"
            try:
                stage_order.append("fetch")
                raw_fetch = fetch_article_body(
                    ref,
                    self.configs,
                    registry=self.source_registry,
                    transport=self.transport,
                )
                fetched_count += 1

                error_stage = "normalize"
                stage_order.append("normalize")
                artifact = normalize_article(raw_fetch)

                error_stage = "artifact_save"
                stage_order.append("artifact_save")
                if self.artifact_store.exists(artifact.article_id):
                    existing_artifact = self.artifact_store.load(artifact.article_id)
                    if existing_artifact.content_hash == artifact.content_hash:
                        artifact = existing_artifact
                    else:
                        self.artifact_store.save(artifact)
                else:
                    self.artifact_store.save(artifact)

                error_stage = "dedupe"
                stage_order.append("dedupe")
                cluster = merge_into_cluster(
                    artifact,
                    self.dedupe_store,
                    threshold=self.dedupe_threshold,
                )
                clustered_artifact = self.dedupe_store.load_article_snapshot(artifact.article_id)
                representative = self.dedupe_store.load_article_snapshot(
                    cluster.representative_article_id
                )

                error_stage = "mention_detect"
                stage_order.append("mention_detect")
                mentions = detect_mentions(representative)

                error_stage = "entity_resolve"
                stage_order.append("entity_resolve")
                entity_resolution = resolve_detected_mentions(mentions, self.entity_client)

                error_stage = "extract"
                stage_order.append("extract")
                facts = extract_facts(
                    representative,
                    cluster,
                    entity_resolution,
                    self.reasoner_client,
                )

                error_stage = "signals"
                stage_order.append("signals")
                signals = generate_signals(facts, self.reasoner_client)

                context = PipelineArticleContext(
                    article_id=clustered_artifact.article_id,
                    cluster_id=cluster.cluster_id,
                    source_reference=clustered_artifact.source_reference,
                    artifact=clustered_artifact,
                    representative_artifact=representative,
                    cluster=cluster,
                    entity_resolution=entity_resolution,
                    facts=facts,
                    signals=signals,
                    schema_pins={"Ex-1": FACT_SCHEMA_PIN, "Ex-2": SIGNAL_SCHEMA_PIN},
                    dedupe_metadata={
                        "threshold": self.dedupe_threshold,
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
                )
                article_results.append(
                    PipelineArticleResult(
                        article_id=clustered_artifact.article_id,
                        source_reference=clustered_artifact.source_reference,
                        status="processed",
                        context=context,
                        candidate_count=len(facts) + len(signals),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - continue and trace per-article failures.
                article_results.append(
                    PipelineArticleResult(
                        article_id=None,
                        source_reference=ref.source_reference,
                        status="failed",
                        error_stage=error_stage,
                        error_message=_error_message(exc),
                    )
                )

        prior_keys = _load_prior_submitted_keys(self.trace_dir)
        (
            article_results,
            submit_receipts,
            submit_error,
        ) = self._submit_or_skip_candidates(article_results, prior_keys, stage_order)
        if submit_error is not None:
            top_level_error = submit_error

        result = self._build_result(
            run_id=run_id,
            started_at=started_at,
            discovered_count=discovered_count,
            fetched_count=fetched_count,
            article_results=article_results,
            submit_receipts=submit_receipts,
            stage_order=stage_order,
            top_level_error=top_level_error,
        )
        return self._write_trace(result, stage_order)

    def _submit_or_skip_candidates(
        self,
        article_results: list[PipelineArticleResult],
        prior_keys: set[str],
        stage_order: list[str],
    ) -> tuple[list[PipelineArticleResult], list[dict[str, object]], str | None]:
        candidate_records: list[tuple[int, CandidatePayload, str]] = []
        submitted_by_article: dict[int, list[str]] = {}
        skipped_by_article: dict[int, list[str]] = {}
        seen_keys: set[str] = set()

        for index, result in enumerate(article_results):
            if result.context is None:
                continue
            for candidate in [*result.context.facts, *result.context.signals]:
                key = candidate_idempotency_key(candidate)
                if key in prior_keys or key in seen_keys:
                    skipped_by_article.setdefault(index, []).append(key)
                    continue
                seen_keys.add(key)
                candidate_records.append((index, candidate, key))

        submit_receipts: list[dict[str, object]] = []
        submit_error: str | None = None

        if not candidate_records:
            return (
                _apply_candidate_counts(
                    article_results,
                    submitted_by_article,
                    skipped_by_article,
                ),
                submit_receipts,
                submit_error,
            )

        if self.dry_run:
            stage_order.append("validate")
            try:
                validate_candidate_batch([candidate for _index, candidate, _key in candidate_records])
            except Exception as exc:  # noqa: BLE001 - trace validation failures.
                submit_error = _error_message(exc)
                return (
                    _apply_candidate_counts(
                        article_results,
                        submitted_by_article,
                        skipped_by_article,
                    ),
                    submit_receipts,
                    submit_error,
                )
            for index, _candidate, key in candidate_records:
                skipped_by_article.setdefault(index, []).append(key)
            return (
                _apply_candidate_counts(
                    article_results,
                    submitted_by_article,
                    skipped_by_article,
                ),
                submit_receipts,
                submit_error,
            )

        iterator = iter(candidate_records)
        while True:
            chunk = list(islice(iterator, self.submit_batch_size))
            if not chunk:
                break
            stage_order.append("validate")
            stage_order.append("submit")
            batch = [candidate for _index, candidate, _key in chunk]
            try:
                receipt = submit_candidates(batch, self.sdk_client)
            except Exception as exc:  # noqa: BLE001 - final failure is reflected in run result.
                submit_error = _error_message(exc)
                break
            submit_receipts.append(receipt.model_dump(mode="json"))
            rejected_ids = set(receipt.rejected_candidate_ids)
            for index, candidate, key in chunk:
                if candidate.candidate_id in rejected_ids:
                    skipped_by_article.setdefault(index, []).append(key)
                else:
                    submitted_by_article.setdefault(index, []).append(key)

        return (
            _apply_candidate_counts(article_results, submitted_by_article, skipped_by_article),
            submit_receipts,
            submit_error,
        )

    def _build_result(
        self,
        *,
        run_id: str,
        started_at: datetime,
        discovered_count: int,
        fetched_count: int,
        article_results: list[PipelineArticleResult],
        submit_receipts: list[dict[str, object]],
        stage_order: list[str],
        top_level_error: str | None,
    ) -> PipelineRunResult:
        submitted_keys = [
            key
            for result in article_results
            for key in result.submitted_candidate_keys
        ]
        skipped_keys = [
            key
            for result in article_results
            for key in result.skipped_candidate_keys
        ]
        return PipelineRunResult(
            run_id=run_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            dry_run=self.dry_run,
            discovered_count=discovered_count,
            fetched_count=fetched_count,
            submitted_count=len(submitted_keys),
            skipped_count=len(skipped_keys),
            error_count=sum(1 for result in article_results if result.status == "failed")
            + (1 if top_level_error is not None else 0),
            article_results=article_results,
            submitted_candidate_keys=submitted_keys,
            skipped_candidate_keys=skipped_keys,
            submit_receipts=submit_receipts,
            stage_order=list(stage_order),
            error_message=top_level_error,
            metadata={"submit_batch_size": self.submit_batch_size},
        )

    def _write_trace(
        self,
        result: PipelineRunResult,
        stage_order: list[str],
    ) -> PipelineRunResult:
        if not stage_order or stage_order[-1] != "trace":
            stage_order.append("trace")
            result = result.model_copy(update={"stage_order": list(stage_order)})
        path = write_pipeline_trace(result, self.trace_dir)
        traced = result.model_copy(update={"trace_path": str(path)})
        write_pipeline_trace(traced, self.trace_dir)
        return traced


def _apply_candidate_counts(
    article_results: list[PipelineArticleResult],
    submitted_by_article: dict[int, list[str]],
    skipped_by_article: dict[int, list[str]],
) -> list[PipelineArticleResult]:
    updated: list[PipelineArticleResult] = []
    for index, result in enumerate(article_results):
        submitted_keys = submitted_by_article.get(index, [])
        skipped_keys = skipped_by_article.get(index, [])
        if result.status == "failed":
            updated.append(result)
            continue
        updated.append(
            result.model_copy(
                update={
                    "submitted_count": len(submitted_keys),
                    "skipped_count": len(skipped_keys),
                    "submitted_candidate_keys": submitted_keys,
                    "skipped_candidate_keys": skipped_keys,
                }
            )
        )
    return updated


def _load_prior_submitted_keys(trace_dir: Path) -> set[str]:
    if not trace_dir.exists():
        return set()
    keys: set[str] = set()
    for path in sorted(trace_dir.glob("*.json")):
        try:
            result = load_pipeline_trace(path)
        except ContractViolationError:
            continue
        keys.update(result.submitted_candidate_keys)
    return keys


def _run_id(started_at: datetime) -> str:
    stamp = started_at.strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(started_at.isoformat().encode("utf-8")).hexdigest()[:8]
    return f"run-{stamp}-{digest}"


def _error_message(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"
