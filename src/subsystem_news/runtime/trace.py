"""Pipeline trace persistence and candidate idempotency helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from subsystem_news.errors import ContractViolationError
from subsystem_news.runtime.models import CandidatePayload, PipelineRunResult


def write_pipeline_trace(result: PipelineRunResult, trace_dir: Path) -> Path:
    """Write one validated pipeline trace JSON file and return its path."""

    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{_safe_run_id(result.run_id)}.json"
    payload = result.model_dump_json(indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path


def load_pipeline_trace(path: Path) -> PipelineRunResult:
    """Load a pipeline trace as a contract model, not a raw dict."""

    try:
        return PipelineRunResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractViolationError("pipeline trace violates PipelineRunResult") from exc


def candidate_idempotency_key(candidate: CandidatePayload) -> str:
    """Return a stable key for duplicate submit suppression."""

    payload: dict[str, Any] = {
        "version": "candidate-idempotency-key.v1",
        "export_contract": candidate.export_contract,
        "candidate_id": candidate.candidate_id,
        "article_id": candidate.article_id,
        "cluster_id": getattr(candidate, "cluster_id", None),
        "source_reference": candidate.source_reference.model_dump(mode="json"),
        "evidence_spans": [
            span.model_dump(mode="json") for span in candidate.evidence_spans
        ],
    }
    if candidate.export_contract == "Ex-3":
        payload["graph_delta"] = {
            "subject_entity": candidate.subject_entity.model_dump(mode="json"),
            "relation_type": candidate.relation_type,
            "object_entity": candidate.object_entity.model_dump(mode="json"),
            "delta_action": candidate.delta_action,
        }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"candidate-key:{digest[:32]}"


def _safe_run_id(run_id: str) -> str:
    if not run_id or run_id.strip() != run_id:
        raise ContractViolationError("run_id must be non-empty without edge whitespace")
    if "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
        raise ContractViolationError("run_id must be safe for local trace storage")
    return run_id
