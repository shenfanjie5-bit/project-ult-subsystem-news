from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from subsystem_news.contracts import load_allowlist
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.entities.resolver_client import RegistryLookup, StubEntityRegistryClient
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.runtime.models import CandidatePayload
from subsystem_news.runtime.pipeline import Pipeline
from subsystem_news.runtime.submit import SubmitReceipt
from subsystem_news.runtime.trace import candidate_idempotency_key, load_pipeline_trace
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


class FakeReasonerRuntimeClient:
    def __init__(self) -> None:
        self.requests: list[StructuredGenerationRequest] = []

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        self.requests.append(request)
        if request.contract == "Ex-1":
            return {"facts": [self._fact_payload(request)]}
        return {"judgement": self._judgement_payload(request)}

    def _fact_payload(self, request: StructuredGenerationRequest) -> dict[str, object]:
        article = request.input_payload["representative_article"]
        if not isinstance(article, Mapping):
            raise AssertionError("representative_article must be a mapping")
        title = str(article["title"])
        body = str(article["body_text"])
        article_id = str(article["article_id"])
        entities = request.input_payload["entity_resolution"]["entities"]  # type: ignore[index]
        if not isinstance(entities, list):
            raise AssertionError("entities must be a list")

        if "North River" in title:
            quote = "North River Metals scheduled routine maintenance"
            fact_type = "supply_chain"
            confidence = 0.5
            summary = "North River Metals scheduled routine maintenance."
            entity = _entity_named(entities, "North River Metals")
        elif "West Retail" in title:
            quote = "West Retail PLC faces a supplier lawsuit"
            fact_type = "litigation"
            confidence = 0.88
            summary = "West Retail faces a supplier lawsuit."
            entity = _entity_named(entities, "West Retail PLC")
        elif "East Power" in title:
            quote = "East Power Ltd signed a grid equipment contract"
            fact_type = "contract"
            confidence = 0.84
            summary = "East Power signed a grid equipment contract."
            entity = _entity_named(entities, "East Power Ltd")
        else:
            quote = "Acme Corp signed a three-year supply contract"
            fact_type = "contract"
            confidence = 0.92
            summary = "Acme signed a supply contract with Globex."
            entity = _entity_named(entities, "Acme Corp")

        start = body.index(quote)
        return {
            "candidate_id": f"fact:{article_id}:{fact_type}",
            "fact_type": fact_type,
            "summary": summary,
            "involved_entities": [entity],
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
            "confidence": confidence,
        }

    def _judgement_payload(self, request: StructuredGenerationRequest) -> dict[str, object]:
        fact = request.input_payload["fact"]
        if not isinstance(fact, Mapping):
            raise AssertionError("fact must be a mapping")
        fact_type = fact["fact_type"]
        if fact_type == "litigation":
            return {
                "signal_type": "event_impact",
                "direction": "negative",
                "impact_scope": "company",
                "time_horizon": "short",
                "rationale": "The lawsuit creates company-specific risk.",
                "confidence": 0.86,
            }
        return {
            "signal_type": "event_impact",
            "direction": "positive",
            "impact_scope": "company",
            "time_horizon": "short",
            "rationale": "The contract supports near-term company revenue.",
            "confidence": 0.84,
        }


class FakeSdkClient:
    def __init__(self) -> None:
        self.calls: list[list[CandidatePayload]] = []

    def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
        submitted = list(batch)
        self.calls.append(submitted)
        return SubmitReceipt(
            accepted_count=len(submitted),
            submitted_candidate_ids=[candidate.candidate_id for candidate in submitted],
        )


class ReceiptSdkClient:
    def __init__(self, receipt_factory: Any) -> None:
        self._receipt_factory = receipt_factory
        self.calls: list[list[CandidatePayload]] = []

    def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
        submitted = list(batch)
        self.calls.append(submitted)
        return self._receipt_factory(submitted)


def test_milestone3_pipeline_runs_sources_to_submit_and_trace(tmp_path: Path) -> None:
    sdk_client = FakeSdkClient()
    pipeline = _pipeline(tmp_path, sdk_client=sdk_client)

    result = pipeline.run()

    assert result.error_count == 0
    assert result.discovered_count == 5
    assert result.fetched_count == 5
    assert result.stage_order[:9] == [
        "discover",
        "fetch",
        "normalize",
        "artifact_save",
        "dedupe",
        "mention_detect",
        "entity_resolve",
        "extract",
        "signals",
    ]
    assert result.stage_order[-3:] == ["validate", "submit", "trace"]
    assert result.submitted_count == len(sdk_client.calls[0])
    assert result.skipped_count >= 2
    assert all(candidate.source_reference is not None for candidate in sdk_client.calls[0])
    assert all(candidate.evidence_spans for candidate in sdk_client.calls[0])

    acme_contexts = [
        article.context
        for article in result.article_results
        if article.context is not None and "Acme Corp" in article.context.artifact.title
    ]
    assert len({context.cluster_id for context in acme_contexts}) == 1

    collision_contexts = [
        article.context
        for article in result.article_results
        if article.context is not None
        and article.context.artifact.source_reference.provider_key == "shared-provider-key"
    ]
    assert len(collision_contexts) == 2
    assert len({context.cluster_id for context in collision_contexts}) == 2

    trace_path = Path(result.trace_path or "")
    assert load_pipeline_trace(trace_path) == result


def test_pipeline_idempotency_skips_candidates_submitted_by_previous_trace(
    tmp_path: Path,
) -> None:
    sdk_client = FakeSdkClient()
    first = _pipeline(tmp_path, sdk_client=sdk_client).run()

    second = _pipeline(tmp_path, sdk_client=sdk_client).run()

    assert first.submitted_count > 0
    assert second.submitted_count == 0
    assert len(sdk_client.calls) == 1
    assert set(first.submitted_candidate_keys).issubset(set(second.skipped_candidate_keys))


def test_pipeline_rejects_ambiguous_submit_receipt_without_marking_submitted(
    tmp_path: Path,
) -> None:
    sdk_client = ReceiptSdkClient(
        lambda _batch: SubmitReceipt(accepted_count=0, rejected_count=0)
    )

    result = _pipeline(tmp_path, sdk_client=sdk_client).run()

    assert len(sdk_client.calls) == 1
    assert result.error_count == 1
    assert result.submitted_count == 0
    assert result.submitted_candidate_keys == []
    assert result.error_message is not None
    assert "counts must equal submitted batch size" in result.error_message


def test_pipeline_records_only_explicitly_accepted_submit_receipt_ids(
    tmp_path: Path,
) -> None:
    def partial_receipt(batch: list[CandidatePayload]) -> SubmitReceipt:
        accepted = batch[:1]
        rejected = batch[1:]
        return SubmitReceipt(
            accepted_count=len(accepted),
            rejected_count=len(rejected),
            submitted_candidate_ids=[candidate.candidate_id for candidate in accepted],
            rejected_candidate_ids=[candidate.candidate_id for candidate in rejected],
        )

    sdk_client = ReceiptSdkClient(partial_receipt)

    result = _pipeline(tmp_path, sdk_client=sdk_client).run()

    accepted_keys = [candidate_idempotency_key(sdk_client.calls[0][0])]
    rejected_keys = {
        candidate_idempotency_key(candidate) for candidate in sdk_client.calls[0][1:]
    }
    assert result.error_count == 0
    assert result.submitted_count == 1
    assert result.submitted_candidate_keys == accepted_keys
    assert rejected_keys.issubset(set(result.skipped_candidate_keys))


def test_pipeline_fails_closed_on_unreadable_prior_trace(tmp_path: Path) -> None:
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    (trace_dir / "corrupt.json").write_text("{not valid json", encoding="utf-8")
    sdk_client = FakeSdkClient()

    result = _pipeline(tmp_path, sdk_client=sdk_client).run()

    assert sdk_client.calls == []
    assert result.error_count == 1
    assert result.submitted_count == 0
    assert result.error_message is not None
    assert "unreadable pipeline trace" in result.error_message
    assert "submit" not in result.stage_order


def _pipeline(tmp_path: Path, *, sdk_client: Any) -> Pipeline:
    return Pipeline(
        configs=load_allowlist(FIXTURE_ROOT / "approved_sources.json"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        dedupe_store=DedupeStore(tmp_path / "dedupe"),
        entity_client=_entity_client(),
        reasoner_client=FakeReasonerRuntimeClient(),
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


def _entity_client() -> StubEntityRegistryClient:
    aliases = {
        name: RegistryLookup(
            canonical_id=f"entity:{name.lower().replace(' ', '-')}",
            canonical_name=name,
            entity_type="company",
            confidence=0.99,
        )
        for name in (
            "Acme Corp",
            "Globex Inc",
            "North River Metals",
            "East Power Ltd",
            "West Retail PLC",
        )
    }
    return StubEntityRegistryClient(alias_results=aliases)


def _entity_named(entities: list[Any], mention_text: str) -> dict[str, object]:
    for entity in entities:
        if isinstance(entity, Mapping) and entity.get("mention_text") == mention_text:
            return dict(entity)
    raise AssertionError(f"missing resolved entity: {mention_text}")
