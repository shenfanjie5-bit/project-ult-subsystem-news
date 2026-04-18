"""Pipeline assembly, submit integration, and replay entry points."""

from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.runtime.backend_config import (
    ReasonerClientFactory,
    RuntimeBackendConfig,
    load_runtime_backend_config,
    resolve_reasoner_client,
)
from subsystem_news.runtime.models import (
    CandidatePayload,
    PipelineArticleContext,
    PipelineArticleResult,
    PipelineConfig,
    PipelineRunResult,
)
from subsystem_news.runtime.orchestrator import run_once
from subsystem_news.runtime.pipeline import Pipeline
from subsystem_news.runtime.replay import (
    ReplayArticleResult,
    ReplayArticleSummary,
    ReplayRunResult,
    ReplayValueDiff,
    replay_artifact_snapshot,
    replay_trace,
)
from subsystem_news.runtime.submit import (
    DefaultSubsystemSdkClient,
    SubmitReceipt,
    SubsystemSdkClient,
    submit_candidates,
    validate_candidate_batch,
)
from subsystem_news.runtime.trace import (
    candidate_idempotency_key,
    load_pipeline_trace,
    write_pipeline_trace,
)

__all__ = [
    "ArtifactStore",
    "CandidatePayload",
    "DefaultSubsystemSdkClient",
    "Pipeline",
    "PipelineArticleContext",
    "PipelineArticleResult",
    "PipelineConfig",
    "PipelineRunResult",
    "ReasonerClientFactory",
    "ReplayArticleResult",
    "ReplayArticleSummary",
    "ReplayRunResult",
    "ReplayValueDiff",
    "RuntimeBackendConfig",
    "SubmitReceipt",
    "SubsystemSdkClient",
    "candidate_idempotency_key",
    "load_runtime_backend_config",
    "load_pipeline_trace",
    "replay_artifact_snapshot",
    "replay_trace",
    "resolve_reasoner_client",
    "run_once",
    "submit_candidates",
    "validate_candidate_batch",
    "write_pipeline_trace",
]
