from __future__ import annotations

from datetime import datetime, timezone

from subsystem_news.runtime.models import PipelineRunResult
from subsystem_news.runtime.trace import (
    candidate_idempotency_key,
    load_pipeline_trace,
    write_pipeline_trace,
)

from .test_submit import fact_candidate, graph_candidate, signal_candidate


def test_candidate_idempotency_key_is_stable_and_contract_sensitive() -> None:
    fact = fact_candidate()

    assert candidate_idempotency_key(fact) == candidate_idempotency_key(fact)
    assert candidate_idempotency_key(fact) != candidate_idempotency_key(signal_candidate())


def test_candidate_idempotency_key_handles_graph_without_cluster_id() -> None:
    graph = graph_candidate()

    assert not hasattr(graph, "cluster_id")
    assert candidate_idempotency_key(graph) == candidate_idempotency_key(graph)
    assert candidate_idempotency_key(graph) != candidate_idempotency_key(fact_candidate())


def test_pipeline_trace_roundtrip_returns_model(tmp_path) -> None:
    result = PipelineRunResult(
        run_id="run-runtime-trace-test",
        started_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 2, 1, 0, 0, 1, tzinfo=timezone.utc),
        dry_run=True,
        discovered_count=1,
        fetched_count=1,
        skipped_count=1,
        skipped_candidate_keys=["candidate-key:abc"],
        stage_order=["discover", "trace"],
    )

    path = write_pipeline_trace(result, tmp_path)
    restored = load_pipeline_trace(path)

    assert isinstance(restored, PipelineRunResult)
    assert restored == result
