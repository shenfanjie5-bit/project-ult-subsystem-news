from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.runtime_client import DefaultReasonerRuntimeClient
from subsystem_news.runtime.backend_config import (
    RuntimeBackendConfig,
    load_runtime_backend_config,
    resolve_reasoner_client,
)
from subsystem_news.runtime.models import PipelineConfig
from subsystem_news.runtime.orchestrator import run_once


def _pipeline_config(tmp_path: Path, *, dry_run: bool = True) -> PipelineConfig:
    return PipelineConfig(
        allowlist_path=tmp_path / "allowlist.json",
        artifact_root=tmp_path / "artifacts",
        dedupe_root=tmp_path / "dedupe",
        trace_root=tmp_path / "trace",
        dry_run=dry_run,
    )


def test_runtime_backend_config_reads_only_provider_neutral_env_values() -> None:
    config = load_runtime_backend_config(
        {
            "SUBSYSTEM_NEWS_REASONER_BACKEND": " fake-runtime ",
            "SUBSYSTEM_NEWS_REASONER_CONFIG_VERSION": " runtime_backend_config.v1 ",
            "SUBSYSTEM_NEWS_REASONER_PROVIDER": " managed-provider ",
            "SUBSYSTEM_NEWS_REASONER_MODEL": " stable-model ",
            "SUBSYSTEM_NEWS_REASONER_FALLBACK_BACKEND": " reasoner-runtime ",
            "SUBSYSTEM_NEWS_REASONER_API_KEY": "must-not-be-read",
        }
    )

    assert config == RuntimeBackendConfig(
        backend_name="fake-runtime",
        config_version="runtime_backend_config.v1",
        provider="managed-provider",
        model="stable-model",
        fallback_backend="reasoner-runtime",
    )
    assert config.extra == {}


def test_runtime_backend_config_defaults_to_reasoner_runtime() -> None:
    sys.modules.pop("reasoner_runtime", None)

    config = load_runtime_backend_config({})
    client = resolve_reasoner_client(config)

    assert config.backend_name == "reasoner-runtime"
    assert config.config_version == "runtime_backend_config.v1"
    assert isinstance(client, DefaultReasonerRuntimeClient)
    assert "reasoner_runtime" not in sys.modules


def test_unknown_backend_fails_closed() -> None:
    config = RuntimeBackendConfig(backend_name="not-registered")

    with pytest.raises(
        ContractViolationError,
        match="unknown reasoner runtime backend: not-registered",
    ):
        resolve_reasoner_client(config)


def test_unknown_backend_config_version_fails_closed() -> None:
    with pytest.raises(ValidationError, match="unsupported runtime backend config_version"):
        RuntimeBackendConfig(config_version="runtime_backend_config.v2")


def test_unknown_fallback_backend_fails_closed() -> None:
    config = RuntimeBackendConfig(
        backend_name="runtime-a",
        fallback_backend="missing-runtime",
    )

    with pytest.raises(
        ContractViolationError,
        match="unknown fallback reasoner runtime backend",
    ):
        resolve_reasoner_client(config, factories={"runtime-a": lambda _: object()})  # type: ignore[return-value]


@pytest.mark.parametrize(
    "payload",
    [
        {"backend_name": ""},
        {"backend_name": "   "},
        {"backend_name": "reasoner-runtime", "unexpected": "value"},
    ],
)
def test_backend_config_invalid_shape_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RuntimeBackendConfig.model_validate(payload)


def test_dry_run_without_explicit_reasoner_does_not_construct_real_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_if_called() -> None:
        raise AssertionError("dry-run must not resolve a real reasoner backend")

    monkeypatch.setattr(
        "subsystem_news.runtime.orchestrator.load_runtime_backend_config",
        _raise_if_called,
    )
    monkeypatch.setattr(
        "subsystem_news.runtime.orchestrator.resolve_reasoner_client",
        _raise_if_called,
    )

    result = run_once(_pipeline_config(tmp_path), configs=[])

    assert result.error_count == 0
