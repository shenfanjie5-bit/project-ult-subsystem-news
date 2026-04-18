"""External runtime entry points without owning scheduling."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from subsystem_news.contracts import NewsSourceConfig, load_allowlist
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.entities.resolver_client import EntityRegistryClient, StubEntityRegistryClient
from subsystem_news.extract.runtime_client import DefaultReasonerRuntimeClient, ReasonerRuntimeClient
from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.runtime.models import PipelineConfig, PipelineRunResult
from subsystem_news.runtime.pipeline import Pipeline
from subsystem_news.runtime.submit import DefaultSubsystemSdkClient, SubmitReceipt, SubsystemSdkClient
from subsystem_news.sources.base import HttpTransport
from subsystem_news.sources.registry import AdapterRegistry


HeartbeatHook = Callable[[str, Mapping[str, object]], None]


def run_once(
    config: PipelineConfig,
    *,
    configs: Sequence[NewsSourceConfig] | None = None,
    artifact_store: ArtifactStore | None = None,
    dedupe_store: DedupeStore | None = None,
    entity_client: EntityRegistryClient | None = None,
    reasoner_client: ReasonerRuntimeClient | None = None,
    sdk_client: SubsystemSdkClient | None = None,
    source_registry: AdapterRegistry | None = None,
    transport: HttpTransport | None = None,
    source_cursor: Mapping[str, str] | None = None,
    heartbeat: HeartbeatHook | None = None,
) -> PipelineRunResult:
    """Run one externally scheduled ingest pass and report heartbeat status."""

    _heartbeat(heartbeat, "started", {"dry_run": config.dry_run})
    try:
        pipeline = Pipeline(
            configs=list(configs) if configs is not None else load_allowlist(config.allowlist_path),
            artifact_store=artifact_store or ArtifactStore(config.artifact_root),
            dedupe_store=dedupe_store or DedupeStore(config.dedupe_root),
            entity_client=entity_client or StubEntityRegistryClient(),
            reasoner_client=reasoner_client
            or (_NoopReasonerRuntimeClient() if config.dry_run else DefaultReasonerRuntimeClient()),
            sdk_client=sdk_client
            or (_NoopSubsystemSdkClient() if config.dry_run else DefaultSubsystemSdkClient()),
            trace_dir=config.trace_root,
            submit_batch_size=config.submit_batch_size,
            dedupe_threshold=config.dedupe_threshold,
            dry_run=config.dry_run,
            source_registry=source_registry,
            transport=transport,
        )
        result = pipeline.run(source_cursor=source_cursor)
    except Exception as exc:
        _heartbeat(heartbeat, "failed", {"error": f"{exc.__class__.__name__}: {exc}"})
        raise

    if result.error_count:
        _heartbeat(
            heartbeat,
            "failed",
            {"run_id": result.run_id, "error_count": result.error_count},
        )
    else:
        _heartbeat(
            heartbeat,
            "completed",
            {"run_id": result.run_id, "submitted_count": result.submitted_count},
        )
    return result


def _heartbeat(
    heartbeat: HeartbeatHook | None,
    status: str,
    payload: Mapping[str, object],
) -> None:
    if heartbeat is not None:
        heartbeat(status, payload)


class _NoopReasonerRuntimeClient:
    def generate_structured(self, request: object) -> Mapping[str, object]:
        del request
        return {"facts": []}


class _NoopSubsystemSdkClient:
    def submit(self, batch: Sequence[object]) -> SubmitReceipt:
        return SubmitReceipt(accepted_count=len(batch))
