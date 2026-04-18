from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.replay_diff import main
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.entities.resolver_client import RegistryLookup, StubEntityRegistryClient
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN
from subsystem_news.fixtures.catalog import FixtureArticleInput, FixtureCase
from subsystem_news.fixtures.loader import load_fixture_suite
from subsystem_news.fixtures.runner import fixture_replay_runner, run_regression_suite
from subsystem_news.graph import GRAPH_SCHEMA_PIN
from subsystem_news.runtime.replay import (
    ReplayRequest,
    diff_replay_results,
    replay_article,
)
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN


MANIFEST = Path("src/subsystem_news/fixtures/regression/manifest.json")
BASELINE_DIR = Path("src/subsystem_news/fixtures/regression/baseline")


def test_unchanged_replay_diff_is_empty() -> None:
    suite = load_fixture_suite(MANIFEST)
    case = suite.cases[0]
    request = ReplayRequest(
        case_id=case.case_id,
        category=case.category,
        article_ids=case.article_ids,
        input_path=case.resolved_baseline_path(suite.root_path),
    )

    diff = diff_replay_results(replay_article(request), replay_article(request))

    assert diff.has_changes is False
    assert diff.candidate_diffs == []
    assert diff.evidence_span_diffs == []
    assert diff.entity_resolution_diffs == []
    assert diff.schema_pin_diffs == []


def test_controlled_changed_output_reports_all_diff_families() -> None:
    suite = load_fixture_suite(MANIFEST)
    suite = suite.model_copy(update={"cases": [suite.cases[0]]})

    report = run_regression_suite(
        suite,
        thresholds=suite.thresholds,
        replay_runner=_changed_replay_runner,
    )

    diff = report.case_results[0].replay_diff
    assert report.passed is False
    assert diff is not None
    assert diff.candidate_diffs
    assert diff.evidence_span_diffs
    assert diff.entity_resolution_diffs
    assert diff.schema_pin_diffs


def test_regression_runner_separates_baseline_from_replay_input() -> None:
    suite = load_fixture_suite(MANIFEST)
    suite = suite.model_copy(update={"cases": [suite.cases[0]]})
    observed: dict[str, Path | None] = {}

    def _snapshot_runner(request: ReplayRequest):
        observed["input_path"] = request.input_path
        observed["baseline_path"] = request.baseline_path
        observed["fixture_case"] = Path(
            request.metadata["fixture_case"]["baseline_path"]
        )
        return replay_article(request.model_copy(update={"input_path": request.baseline_path}))

    report = run_regression_suite(
        suite,
        thresholds=suite.thresholds,
        replay_runner=_snapshot_runner,
    )

    assert report.passed is True
    assert observed["baseline_path"] == suite.cases[0].resolved_baseline_path(
        suite.root_path
    )
    assert observed["input_path"] == MANIFEST
    assert observed["input_path"] != observed["baseline_path"]
    assert observed["fixture_case"] == Path("baseline/single_source.json")


def test_missing_candidate_payloads_fail_without_expected_metric_fallback() -> None:
    suite = load_fixture_suite(MANIFEST)
    suite = suite.model_copy(update={"cases": [suite.cases[0]]})

    report = run_regression_suite(
        suite,
        thresholds=suite.thresholds,
        replay_runner=_metadata_without_candidate_payloads,
    )

    result = report.case_results[0]
    assert report.passed is False
    assert result.status == "failed"
    assert result.metrics["missing_candidate_payloads"] == 1.0
    assert result.metrics["actual_candidate_count"] == 0.0
    assert report.metrics["evidence_coverage"] == 0.0
    assert report.metrics["ex2_contract_completeness"] == 0.0


def test_default_fixture_replay_runner_fails_fast_without_entity_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUBSYSTEM_NEWS_ENTITY_REGISTRY_URL", raising=False)
    monkeypatch.delenv("ENTITY_REGISTRY_URL", raising=False)

    with pytest.raises(ContractViolationError, match="fixture replay requires"):
        fixture_replay_runner()


def test_fixture_replay_runner_executes_runtime_path_from_fixture_inputs(
    tmp_path: Path,
) -> None:
    published_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    fetched_at = datetime(2026, 3, 1, 0, 5, tzinfo=timezone.utc)
    source_reference = SourceReference.model_validate(
        {
            "source_id": "fixture-wire",
            "url": "https://fixtures.example.com/news/acme-contract",
            "provider_key": "acme-contract",
            "original_locator": {
                "locator_type": "fixture",
                "locator_value": "acme-contract",
            },
        }
    )
    raw_input = FixtureArticleInput(
        article_id="article-fixture-real-replay",
        source_reference=source_reference,
        title="Acme Corp contract update",
        body_text="Acme Corp signed a supply contract with Beta Inc.",
        published_at=published_at,
        fetched_at=fetched_at,
    )
    case = FixtureCase(
        case_id="fixture-real-replay",
        category="single_source",
        article_ids=[raw_input.article_id],
        expected_outputs=[],
        source_reference=source_reference,
        version_pins={
            "Ex-1": FACT_SCHEMA_PIN,
            "Ex-2": SIGNAL_SCHEMA_PIN,
            "Ex-3": GRAPH_SCHEMA_PIN,
        },
        baseline_path=str(tmp_path / "baseline.json"),
        raw_inputs=[raw_input],
    )
    runner = fixture_replay_runner(
        entity_client=StubEntityRegistryClient(
            alias_results={
                "Acme Corp": RegistryLookup(
                    canonical_id="entity:acme-corp",
                    canonical_name="Acme Corp",
                    entity_type="company",
                    confidence=0.99,
                ),
                "Beta Inc": RegistryLookup(
                    canonical_id="entity:beta-inc",
                    canonical_name="Beta Inc",
                    entity_type="company",
                    confidence=0.99,
                ),
            }
        ),
        reasoner_client=_FixtureReplayReasoner(),
    )

    result = runner(
        ReplayRequest(
            case_id=case.case_id,
            category=case.category,
            article_ids=case.article_ids,
            input_path=Path("fixture-real-replay/cases.json"),
            baseline_path=tmp_path / "baseline.json",
            metadata={"fixture_case": case.model_dump(mode="json")},
        )
    )

    assert result.error_count == 0
    assert result.input_path == "fixture-real-replay/cases.json"
    assert result.stage_order[:3] == ["load_fixture", "normalize", "dedupe"]
    assert {"mention_detect", "entity_resolve", "extract", "signals", "graph"} <= set(
        result.stage_order
    )
    assert result.metadata["candidate_payloads"]
    assert {
        payload["export_contract"] for payload in result.metadata["candidate_payloads"]
    } == {"Ex-1", "Ex-2"}


def test_replay_diff_cli_fails_fast_without_replay_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUBSYSTEM_NEWS_ENTITY_REGISTRY_URL", raising=False)
    monkeypatch.delenv("ENTITY_REGISTRY_URL", raising=False)

    with pytest.raises(ContractViolationError, match="fixture replay requires"):
        main(
            [
                "--suite",
                str(MANIFEST),
                "--baseline-dir",
                str(BASELINE_DIR),
                "--output-dir",
                str(tmp_path),
                "--json",
                "--markdown",
                "--fail-on-regression",
            ]
        )


def test_replay_diff_cli_returns_nonzero_for_threshold_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_dir = tmp_path / "baseline"
    shutil.copytree(BASELINE_DIR, baseline_dir)
    negative_path = baseline_dir / "graph_negative.json"
    positive_path = baseline_dir / "graph_positive.json"
    negative = json.loads(negative_path.read_text(encoding="utf-8"))
    positive = json.loads(positive_path.read_text(encoding="utf-8"))
    graph_payload = next(
        payload
        for payload in positive["metadata"]["candidate_payloads"]
        if payload["export_contract"] == "Ex-3"
    )
    target_payload = negative["metadata"]["candidate_payloads"][0]
    graph_payload = {
        **graph_payload,
        "candidate_id": "graph-negative-injected-false-positive",
        "article_id": target_payload["article_id"],
        "source_reference": target_payload["source_reference"],
        "evidence_spans": target_payload["evidence_spans"],
    }
    negative["metadata"]["candidate_payloads"].append(graph_payload)
    negative_path.write_text(json.dumps(negative, indent=2) + "\n", encoding="utf-8")

    def _run_snapshot_suite(suite, *, thresholds):
        return run_regression_suite(
            suite,
            thresholds=thresholds,
            replay_runner=_load_replay_from_baseline_path,
        )

    monkeypatch.setattr("scripts.replay_diff.run_regression_suite", _run_snapshot_suite)
    exit_code = main(
        [
            "--suite",
            str(MANIFEST),
            "--baseline-dir",
            str(baseline_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--json",
            "--fail-on-regression",
        ]
    )

    assert exit_code == 1
    report = json.loads((tmp_path / "out" / "replay_report.json").read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["metrics"]["ex3_false_positive_rate"] > 0.01


def _changed_replay_runner(request: ReplayRequest):
    result = replay_article(request.model_copy(update={"input_path": request.baseline_path}))
    metadata = json.loads(json.dumps(result.metadata))
    metadata["candidate_payloads"][0]["candidate_id"] += "-changed"

    evidence_key = next(iter(metadata["evidence_spans"]))
    metadata["evidence_spans"][evidence_key]["quote"] += " changed"

    entity_key = next(iter(metadata["entity_resolutions"]))
    metadata["entity_resolutions"][entity_key]["canonical_id"] = "entity:changed"

    metadata["schema_pins"]["Ex-1"]["schema_version"] = "news_fact_candidate.changed"
    return result.model_copy(update={"metadata": metadata})


def _metadata_without_candidate_payloads(request: ReplayRequest):
    result = replay_article(request.model_copy(update={"input_path": request.baseline_path}))
    return result.model_copy(update={"metadata": {"article_count": 1}})


def _load_replay_from_baseline_path(request: ReplayRequest):
    return replay_article(request.model_copy(update={"input_path": request.baseline_path}))


class _FixtureReplayReasoner:
    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        if request.contract == "Ex-1":
            article = request.input_payload["representative_article"]
            if not isinstance(article, Mapping):
                raise AssertionError("representative_article must be a mapping")
            body = str(article["body_text"])
            quote = "Acme Corp signed a supply contract"
            start = body.index(quote)
            entities = request.input_payload["entity_resolution"]["entities"]  # type: ignore[index]
            if not isinstance(entities, list):
                raise AssertionError("entities must be a list")
            return {
                "facts": [
                    {
                        "candidate_id": "fact-fixture-real-contract",
                        "fact_type": "contract",
                        "summary": "Acme signed a supply contract.",
                        "involved_entities": [
                            _entity_named(entities, "Acme Corp"),
                        ],
                        "event_time": None,
                        "evidence_spans": [
                            {
                                "article_id": article["article_id"],
                                "start_char": start,
                                "end_char": start + len(quote),
                                "quote": quote,
                                "locator": "body",
                            }
                        ],
                        "confidence": 0.9,
                    }
                ]
            }
        if request.contract == "Ex-3":
            return {"graph_deltas": []}
        return {
            "judgement": {
                "signal_type": "event_impact",
                "direction": "positive",
                "impact_scope": "company",
                "time_horizon": "short",
                "rationale": "The contract supports company revenue.",
                "confidence": 0.84,
            }
        }


def _entity_named(entities: list[object], mention_text: str) -> dict[str, object]:
    for entity in entities:
        if isinstance(entity, Mapping) and entity.get("mention_text") == mention_text:
            return dict(entity)
    raise AssertionError(f"missing entity {mention_text}")
