from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from subsystem_news.contracts import load_allowlist
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.runtime.models import CandidatePayload
from subsystem_news.runtime.pipeline import Pipeline
from subsystem_news.runtime.trace import load_pipeline_trace

from tests.integration.test_milestone3_pipeline import (
    FIXTURE_ROOT,
    FakeReasonerRuntimeClient,
    FakeSdkClient,
    StaticTransport,
    _entity_client,
    _entity_named,
)


class GraphReasonerRuntimeClient(FakeReasonerRuntimeClient):
    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        if request.contract != "Ex-3":
            return super().generate_structured(request)

        self.requests.append(request)
        article = request.input_payload["representative_article"]
        if not isinstance(article, Mapping):
            raise AssertionError("representative_article must be a mapping")
        body = str(article["body_text"])
        if "Acme Corp" not in body:
            return {"graph_deltas": []}

        entities = request.input_payload["entity_resolution"]["entities"]  # type: ignore[index]
        if not isinstance(entities, list):
            raise AssertionError("entities must be a list")
        quote = "Acme Corp signed a three-year supply contract with Globex Inc"
        start = body.index(quote)
        return {
            "graph_deltas": [
                {
                    "subject_entity": _entity_named(entities, "Acme Corp"),
                    "relation_type": "supplier_of",
                    "object_entity": _entity_named(entities, "Globex Inc"),
                    "delta_action": "add",
                    "valid_from": None,
                    "evidence_spans": [
                        {
                            "article_id": article["article_id"],
                            "start_char": start,
                            "end_char": start + len(quote),
                            "quote": quote,
                            "locator": "body",
                        }
                    ],
                    "confidence": 0.91,
                }
            ]
        }


def test_milestone4_pipeline_submits_graph_delta_and_traces_schema_pin(
    tmp_path: Path,
) -> None:
    sdk_client = FakeSdkClient()
    pipeline = Pipeline(
        configs=load_allowlist(FIXTURE_ROOT / "approved_sources.json"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        dedupe_store=DedupeStore(tmp_path / "dedupe"),
        entity_client=_entity_client(),
        reasoner_client=GraphReasonerRuntimeClient(),
        sdk_client=sdk_client,
        trace_dir=tmp_path / "trace",
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

    result = pipeline.run()

    submitted: list[CandidatePayload] = sdk_client.calls[0]
    graph_deltas = [
        candidate for candidate in submitted if candidate.export_contract == "Ex-3"
    ]
    assert result.error_count == 0
    assert "graph" in result.stage_order
    assert graph_deltas
    assert all(candidate.requires_manual_review for candidate in graph_deltas)
    assert submitted.index(graph_deltas[0]) > submitted.index(
        next(candidate for candidate in submitted if candidate.export_contract == "Ex-2")
    )

    acme_context = next(
        article.context
        for article in result.article_results
        if article.context is not None and article.context.graph_deltas
    )
    assert acme_context.schema_pins["Ex-3"].contract == "Ex-3"
    assert acme_context.graph_metadata == {"graph_delta_count": 1}

    restored = load_pipeline_trace(Path(result.trace_path or ""))
    restored_context = next(
        article.context
        for article in restored.article_results
        if article.context is not None and article.context.graph_deltas
    )
    assert restored_context.schema_pins["Ex-3"].schema_name == "news_graph_delta_candidate"
    assert restored_context.graph_deltas[0].relation_type == "supplier_of"
