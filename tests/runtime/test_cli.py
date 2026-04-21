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


def test_cli_ingest_non_dry_run_with_sdk_backend_mock_wires_sdk_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 2.9 follow-up #3 (codex review #3 P3 #1): positive
    regression test that ``main(... --sdk-backend mock)`` actually
    takes the non-dry-run branch, enters
    ``configure_runtime(default_news_subsystem_context())``, and
    passes an explicit ``DefaultSubsystemSdkClient`` into
    ``run_once()``. Without this test the follow-up #2 fix is only
    protected by manual smoke.

    Patches ``run_once`` to capture the call args + return a benign
    result so the CLI doesn't progress further into entity-registry /
    HTTP wiring requirements (which are pre-existing non-dry-run
    guards unrelated to the SDK wiring fix this test asserts).
    """

    from datetime import UTC, datetime

    from subsystem_news.runtime.models import PipelineRunResult
    from subsystem_news.runtime.submit import DefaultSubsystemSdkClient
    from subsystem_sdk.base.runtime import _SCOPED_RUNTIME

    captured_kwargs: dict = {}
    captured_runtime_during_call: list = []

    def fake_run_once(config, **kwargs):
        captured_kwargs.update(kwargs)
        captured_kwargs["config"] = config
        # Snapshot the active runtime SDK context so the test can
        # confirm configure_runtime() was active when run_once was
        # invoked (proves the CLI wired SDK runtime, not just passed
        # sdk_client= at the call site).
        captured_runtime_during_call.append(_SCOPED_RUNTIME.get())
        now = datetime(2026, 1, 1, tzinfo=UTC)
        return PipelineRunResult(
            run_id="cli-positive-test-run",
            started_at=now,
            completed_at=now,
            dry_run=False,
            stage_order=[],
            article_results=[],
            submitted_count=0,
            error_count=0,
            trace_path=None,
        )

    # Patch the symbol the CLI module imported, NOT the original
    # function in orchestrator.py — `from subsystem_news.runtime.orchestrator
    # import run_once` binds to a local name in the CLI module.
    import subsystem_news.runtime.cli as cli_module

    monkeypatch.setattr(cli_module, "run_once", fake_run_once)

    exit_code = main(
        [
            "ingest",
            "--allowlist",
            "src/subsystem_news/fixtures/approved_sources.valid.sample.json",
            "--state-dir",
            str(tmp_path / "state"),
            "--trace-dir",
            str(tmp_path / "trace"),
            "--sdk-backend",
            "mock",
        ]
    )

    assert exit_code == 0
    # 1) sdk_client was explicitly passed (not None) and is the
    #    DefaultSubsystemSdkClient (NOT _NoopSubsystemSdkClient).
    assert "sdk_client" in captured_kwargs, (
        f"CLI must pass sdk_client= explicitly in non-dry-run mode; "
        f"got kwargs: {sorted(captured_kwargs)}"
    )
    sdk_client = captured_kwargs["sdk_client"]
    assert isinstance(sdk_client, DefaultSubsystemSdkClient), (
        f"CLI must wire DefaultSubsystemSdkClient for --sdk-backend mock; "
        f"got {type(sdk_client).__name__}"
    )
    # 2) PipelineConfig.dry_run is False (so orchestrator takes the
    #    non-dry-run branch — proves --sdk-backend mock didn't
    #    accidentally switch on dry_run).
    assert captured_kwargs["config"].dry_run is False
    # 3) configure_runtime() was active during run_once invocation
    #    (proves the CLI wrapped run_once in configure_runtime, not
    #    just constructed a context separately).
    assert len(captured_runtime_during_call) == 1
    assert captured_runtime_during_call[0] is not None, (
        "configure_runtime() context manager must be active when "
        "run_once is called from the non-dry-run CLI branch"
    )
