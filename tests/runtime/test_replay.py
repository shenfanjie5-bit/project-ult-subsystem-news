from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from subsystem_news.contracts import load_allowlist
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.entities.resolver_client import RegistryLookup, StubEntityRegistryClient
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN
from subsystem_news.graph import GRAPH_SCHEMA_PIN
from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.runtime.cli import main
from subsystem_news.runtime.models import CandidatePayload, PipelineRunResult
from subsystem_news.runtime.pipeline import Pipeline
from subsystem_news.runtime.replay import replay_artifact_snapshot, replay_trace
from subsystem_news.runtime.submit import SubmitReceipt
from subsystem_news.runtime.trace import write_pipeline_trace
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN
from subsystem_news.sources.base import HttpResponse


FIXTURE_ROOT = Path("src/subsystem_news/fixtures/runtime")


class StaticTransport:
    def __init__(self, responses: Mapping[str, str]) -> None:
        self._responses = responses

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        del headers
        return HttpResponse(url=url, status_code=200, text=self._responses[url], headers={})


class ReplayReasonerRuntimeClient:
    def __init__(self, *, changed_acme_evidence: bool = False) -> None:
        self.changed_acme_evidence = changed_acme_evidence
        self.requests: list[StructuredGenerationRequest] = []

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        self.requests.append(request)
        if request.contract == "Ex-1":
            return {"facts": [self._fact_payload(request)]}
        if request.contract == "Ex-3":
            return {"graph_deltas": []}
        return {"judgement": self._judgement_payload(request)}

    def _fact_payload(self, request: StructuredGenerationRequest) -> dict[str, object]:
        article = request.input_payload["representative_article"]
        if not isinstance(article, Mapping):
            raise AssertionError("representative_article must be a mapping")
        body = str(article["body_text"])
        article_id = str(article["article_id"])
        entities = request.input_payload["entity_resolution"]["entities"]  # type: ignore[index]
        if not isinstance(entities, list):
            raise AssertionError("entities must be a list")

        fact_type = "litigation" if "lawsuit" in body else "contract"
        quote = _quote_for_body(body, changed_acme_evidence=self.changed_acme_evidence)
        start = body.index(quote)
        return {
            "candidate_id": f"fact:{article_id}:{fact_type}",
            "fact_type": fact_type,
            "summary": f"{fact_type} event for replay.",
            "involved_entities": [_first_resolved_entity(entities)],
            "event_time": None,
            "evidence_spans": [
                {
                    "article_id": article_id,
                    "start_char": start,
                    "end_char": start + len(quote),
                    "quote": quote,
                    "locator": "body",
                }
            ],
            "confidence": 0.9,
        }

    def _judgement_payload(self, request: StructuredGenerationRequest) -> dict[str, object]:
        fact = request.input_payload["fact"]
        if not isinstance(fact, Mapping):
            raise AssertionError("fact must be a mapping")
        direction = "negative" if fact["fact_type"] == "litigation" else "positive"
        return {
            "signal_type": "event_impact",
            "direction": direction,
            "impact_scope": "company",
            "time_horizon": "short",
            "rationale": "Replay fixture judgement.",
            "confidence": 0.86,
        }


class NoopSdkClient:
    def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
        return SubmitReceipt(
            accepted_count=len(batch),
            submitted_candidate_ids=[candidate.candidate_id for candidate in batch],
        )


def test_replay_trace_unchanged_has_no_diffs_and_preserves_schema_pins(
    tmp_path: Path,
) -> None:
    baseline = _pipeline(tmp_path, reasoner=ReplayReasonerRuntimeClient()).run()

    replay_reasoner = ReplayReasonerRuntimeClient()
    result = replay_trace(
        Path(baseline.trace_path or ""),
        entity_client=_entity_client(),
        reasoner_client=replay_reasoner,
    )

    assert result.error_count == 0
    assert result.changed_count == 0
    assert result.has_changes is False
    assert result.source_run_id == baseline.run_id
    assert result.article_results
    assert result.metadata["article_count"] == len(result.article_results)
    assert result.metadata["candidate_payloads"]
    assert result.metadata["evidence_spans"]
    assert result.metadata["entity_resolutions"]
    assert result.metadata["schema_pins"]["Ex-1"]["schema_version"] == (
        FACT_SCHEMA_PIN.schema_version
    )
    assert all(not article.has_changes for article in result.article_results)
    assert all(not article.candidate_diffs for article in result.article_results)
    assert all(not article.evidence_span_diffs for article in result.article_results)
    assert all(not article.entity_resolution_diffs for article in result.article_results)
    assert all(not article.version_metadata_diffs for article in result.article_results)
    assert all(
        article.baseline is not None
        and article.replayed is not None
        and article.baseline.schema_pins == article.replayed.schema_pins
        for article in result.article_results
    )
    assert _request_pins(replay_reasoner.requests) == {
        (
            "Ex-1",
            FACT_SCHEMA_PIN.schema_name,
            FACT_SCHEMA_PIN.schema_version,
            FACT_SCHEMA_PIN.model_output_version,
        ),
        (
            "Ex-2",
            SIGNAL_SCHEMA_PIN.schema_name,
            SIGNAL_SCHEMA_PIN.schema_version,
            SIGNAL_SCHEMA_PIN.model_output_version,
        ),
        (
            "Ex-3",
            GRAPH_SCHEMA_PIN.schema_name,
            GRAPH_SCHEMA_PIN.schema_version,
            GRAPH_SCHEMA_PIN.model_output_version,
        ),
    }


def test_replay_trace_reports_controlled_changed_output(tmp_path: Path) -> None:
    baseline = _pipeline(tmp_path, reasoner=ReplayReasonerRuntimeClient()).run()

    result = replay_trace(
        Path(baseline.trace_path or ""),
        entity_client=_entity_client(acme_canonical_id="entity:acme-v2"),
        reasoner_client=ReplayReasonerRuntimeClient(changed_acme_evidence=True),
    )

    changed_articles = [article for article in result.article_results if article.has_changes]
    assert result.error_count == 0
    assert result.changed_count >= 1
    assert changed_articles
    assert any(article.candidate_diffs for article in changed_articles)
    assert any(article.evidence_span_diffs for article in changed_articles)
    assert any(article.entity_resolution_diffs for article in changed_articles)
    assert all(not article.version_metadata_diffs for article in result.article_results)


def test_replay_artifact_snapshot_runs_without_baseline(tmp_path: Path) -> None:
    baseline = _pipeline(tmp_path, reasoner=ReplayReasonerRuntimeClient()).run()
    context = next(article.context for article in baseline.article_results if article.context)
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(context.artifact.model_dump_json(indent=2), encoding="utf-8")

    result = replay_artifact_snapshot(
        artifact_path,
        entity_client=_entity_client(),
        reasoner_client=ReplayReasonerRuntimeClient(),
    )

    assert result.error_count == 0
    assert result.changed_count == 0
    assert result.input_kind == "artifact"
    assert len(result.article_results) == 1
    article = result.article_results[0]
    assert article.baseline_available is False
    assert article.replayed is not None
    assert article.replayed.candidate_ids


def test_cli_replay_dry_run_emits_structured_json(
    tmp_path: Path,
    capsys,
) -> None:
    trace_path = write_pipeline_trace(
        PipelineRunResult(
            run_id="run-replay-cli-test",
            started_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 2, 1, 0, 0, 1, tzinfo=timezone.utc),
            dry_run=True,
            stage_order=["discover", "trace"],
        ),
        tmp_path,
    )

    exit_code = main(["replay", "--trace", str(trace_path), "--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["input_kind"] == "trace"
    assert payload["source_run_id"] == "run-replay-cli-test"
    assert payload["changed_count"] == 0
    assert payload["error_count"] == 0


def _pipeline(tmp_path: Path, *, reasoner: ReplayReasonerRuntimeClient) -> Pipeline:
    return Pipeline(
        configs=load_allowlist(FIXTURE_ROOT / "approved_sources.json"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        dedupe_store=DedupeStore(tmp_path / "dedupe"),
        entity_client=_entity_client(),
        reasoner_client=reasoner,
        sdk_client=NoopSdkClient(),
        trace_dir=tmp_path / "trace",
        dry_run=True,
        transport=StaticTransport(
            {
                "https://runtime.example.com/api/primary": (
                    FIXTURE_ROOT / "primary_api_response.json"
                ).read_text(encoding="utf-8"),
                "https://runtime.example.com/api/secondary": (
                    FIXTURE_ROOT / "secondary_api_response.json"
                ).read_text(encoding="utf-8"),
            }
        ),
    )


def _entity_client(*, acme_canonical_id: str = "entity:acme") -> StubEntityRegistryClient:
    aliases = {
        "Acme Corp": RegistryLookup(
            canonical_id=acme_canonical_id,
            canonical_name="Acme Corp",
            entity_type="company",
            confidence=0.99,
        )
    }
    for name in (
        "Globex Inc",
        "North River Metals",
        "East Power Ltd",
        "West Retail PLC",
    ):
        aliases[name] = RegistryLookup(
            canonical_id=f"entity:{name.lower().replace(' ', '-')}",
            canonical_name=name,
            entity_type="company",
            confidence=0.99,
        )
    return StubEntityRegistryClient(alias_results=aliases)


def _quote_for_body(body: str, *, changed_acme_evidence: bool) -> str:
    if changed_acme_evidence and "Acme Corp signed" in body:
        return "Acme Corp signed a three-year supply contract with Globex Inc"
    if "Acme Corp signed" in body:
        return "Acme Corp signed a three-year supply contract"
    return body.split(" for ", maxsplit=1)[0]


def _first_resolved_entity(entities: list[Any]) -> dict[str, object]:
    for entity in entities:
        if isinstance(entity, Mapping) and entity.get("resolution_status") == "resolved":
            return dict(entity)
    raise AssertionError("expected at least one resolved entity")


def _request_pins(
    requests: Sequence[StructuredGenerationRequest],
) -> set[tuple[str, str, str, str]]:
    return {
        (
            request.contract,
            request.schema_name,
            request.schema_version,
            request.model_output_version,
        )
        for request in requests
    }
