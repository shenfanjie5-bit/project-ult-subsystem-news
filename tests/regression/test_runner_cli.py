from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.replay_diff import main
from subsystem_news.fixtures.loader import load_fixture_suite
from subsystem_news.fixtures.runner import run_regression_suite
from subsystem_news.runtime.replay import (
    ReplayRequest,
    diff_replay_results,
    replay_article,
)


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


def test_replay_diff_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    exit_code = main(
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

    report_json = json.loads((tmp_path / "replay_report.json").read_text(encoding="utf-8"))
    report_markdown = (tmp_path / "replay_report.md").read_text(encoding="utf-8")
    assert exit_code == 0
    assert report_json["passed"] is True
    assert "Regression Replay Report" in report_markdown
    assert "`evidence_coverage`: 1.0000" in report_markdown


def test_replay_diff_cli_returns_nonzero_for_threshold_failure(tmp_path: Path) -> None:
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
    negative["metadata"]["candidate_payloads"].append(graph_payload)
    negative_path.write_text(json.dumps(negative, indent=2) + "\n", encoding="utf-8")

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
    result = replay_article(request)
    metadata = json.loads(json.dumps(result.metadata))
    metadata["candidate_payloads"][0]["candidate_id"] += "-changed"

    evidence_key = next(iter(metadata["evidence_spans"]))
    metadata["evidence_spans"][evidence_key]["quote"] += " changed"

    entity_key = next(iter(metadata["entity_resolutions"]))
    metadata["entity_resolutions"][entity_key]["canonical_id"] = "entity:changed"

    metadata["schema_pins"]["Ex-1"]["schema_version"] = "news_fact_candidate.changed"
    return result.model_copy(update={"metadata": metadata})
