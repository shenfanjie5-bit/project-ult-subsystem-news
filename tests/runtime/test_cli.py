from __future__ import annotations

from pathlib import Path

import pytest

from subsystem_news.runtime.cli import main
from subsystem_news.runtime.trace import load_pipeline_trace


def test_cli_ingest_dry_run_writes_trace_without_submit(tmp_path: Path) -> None:
    trace_dir = tmp_path / "trace"
    exit_code = main(
        [
            "ingest",
            "--allowlist",
            "src/subsystem_news/fixtures/approved_sources.valid.sample.json",
            "--state-dir",
            str(tmp_path / "state"),
            "--trace-dir",
            str(trace_dir),
            "--dry-run",
        ]
    )

    traces = list(trace_dir.glob("*.json"))
    assert exit_code == 0
    assert len(traces) == 1
    result = load_pipeline_trace(traces[0])
    assert result.dry_run is True
    assert result.submitted_count == 0
    assert "submit" not in result.stage_order


def test_cli_ingest_non_dry_run_without_sdk_backend_rejected(
    tmp_path: Path,
) -> None:
    """Stage 2.9 follow-up #2 (codex review #2 P2): non-dry-run requires
    explicit ``--sdk-backend``. Argparse rejects (exit 2) rather than
    crashing later inside orchestrator with a cryptic error.
    """

    trace_dir = tmp_path / "trace"
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "ingest",
                "--allowlist",
                "src/subsystem_news/fixtures/approved_sources.valid.sample.json",
                "--state-dir",
                str(tmp_path / "state"),
                "--trace-dir",
                str(trace_dir),
                # No --sdk-backend, no --dry-run.
            ]
        )
    assert excinfo.value.code == 2  # argparse error
