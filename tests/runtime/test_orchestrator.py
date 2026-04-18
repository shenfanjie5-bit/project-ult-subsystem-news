from __future__ import annotations

from pathlib import Path

import pytest

from subsystem_news.runtime.models import PipelineConfig
from subsystem_news.runtime.orchestrator import run_once


def config(tmp_path: Path, *, dry_run: bool = True) -> PipelineConfig:
    return PipelineConfig(
        allowlist_path=tmp_path / "allowlist.json",
        artifact_root=tmp_path / "artifacts",
        dedupe_root=tmp_path / "dedupe",
        trace_root=tmp_path / "trace",
        dry_run=dry_run,
    )


def test_run_once_heartbeat_records_started_and_completed(tmp_path: Path) -> None:
    events: list[str] = []

    result = run_once(
        config(tmp_path),
        configs=[],
        heartbeat=lambda status, payload: events.append(status),
    )

    assert result.error_count == 0
    assert events == ["started", "completed"]


def test_run_once_heartbeat_records_failed_setup(tmp_path: Path) -> None:
    events: list[str] = []

    with pytest.raises(FileNotFoundError):
        run_once(
            config(tmp_path),
            heartbeat=lambda status, payload: events.append(status),
        )

    assert events == ["started", "failed"]
