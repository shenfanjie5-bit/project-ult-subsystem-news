#!/usr/bin/env python3
"""Generate replay regression diff reports from checked-in fixtures."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from subsystem_news.fixtures.catalog import FixtureSuite, RegressionReport
from subsystem_news.fixtures.loader import load_fixture_suite
from subsystem_news.fixtures.runner import run_regression_suite


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, help="Path to regression manifest.json")
    parser.add_argument("--baseline-dir", required=True, help="Directory with baseline JSON")
    parser.add_argument("--output-dir", required=True, help="Directory for generated reports")
    parser.add_argument("--json", action="store_true", help="Write replay_report.json")
    parser.add_argument("--markdown", action="store_true", help="Write replay_report.md")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Return non-zero when thresholds or cases fail",
    )
    args = parser.parse_args(argv)

    suite = load_fixture_suite(Path(args.suite))
    suite = _with_baseline_dir(suite, Path(args.baseline_dir))
    report = run_regression_suite(suite, thresholds=suite.thresholds)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.json or not args.markdown:
        (output_dir / "replay_report.json").write_text(
            report.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    if args.markdown:
        (output_dir / "replay_report.md").write_text(
            _markdown_report(report),
            encoding="utf-8",
        )

    print(json.dumps(_summary_payload(report), ensure_ascii=False, sort_keys=True))
    if args.fail_on_regression and not report.passed:
        return 1
    return 0


def _with_baseline_dir(suite: FixtureSuite, baseline_dir: Path) -> FixtureSuite:
    cases = []
    for case in suite.cases:
        baseline_name = Path(case.baseline_path).name
        cases.append(case.model_copy(update={"baseline_path": str(baseline_dir / baseline_name)}))
    return suite.model_copy(update={"cases": cases, "root_path": None})


def _markdown_report(report: RegressionReport) -> str:
    lines = [
        "# Regression Replay Report",
        "",
        f"- Suite: `{report.suite_id}`",
        f"- Version: `{report.suite_version}`",
        f"- Passed: `{str(report.passed).lower()}`",
        "",
        "## Metrics",
        "",
    ]
    for name, value in sorted(report.metrics.items()):
        lines.append(f"- `{name}`: {value:.4f}")
    lines.extend(["", "## Cases", ""])
    for result in report.case_results:
        lines.append(
            f"- `{result.case_id}` ({result.category}): `{result.status}`"
        )
        if result.replay_diff is not None and result.replay_diff.has_changes:
            lines.append(
                "  - diffs: "
                f"candidates={len(result.replay_diff.candidate_diffs)}, "
                f"evidence={len(result.replay_diff.evidence_span_diffs)}, "
                f"entities={len(result.replay_diff.entity_resolution_diffs)}, "
                f"schema={len(result.replay_diff.schema_pin_diffs)}"
            )
        if result.replay_error:
            lines.append(f"  - error: {result.replay_error}")
    if report.threshold_violations:
        lines.extend(["", "## Threshold Violations", ""])
        lines.extend(f"- {violation}" for violation in report.threshold_violations)
    return "\n".join(lines) + "\n"


def _summary_payload(report: RegressionReport) -> dict[str, object]:
    return {
        "suite_id": report.suite_id,
        "suite_version": report.suite_version,
        "passed": report.passed,
        "metrics": report.metrics,
        "threshold_violations": report.threshold_violations,
        "case_count": len(report.case_results),
        "failed_case_count": report.failed_case_count,
    }


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
