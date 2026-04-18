from __future__ import annotations

from pathlib import Path

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
