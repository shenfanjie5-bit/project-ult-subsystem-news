"""Provider-neutral reasoner runtime backend configuration."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.runtime_client import (
    DefaultReasonerRuntimeClient,
    ReasonerRuntimeClient,
)


_DEFAULT_BACKEND_NAME = "reasoner-runtime"
_DEFAULT_CONFIG_VERSION = "runtime_backend_config.v1"
_ALLOWED_CONFIG_VERSIONS = frozenset({_DEFAULT_CONFIG_VERSION})


class RuntimeBackendConfig(BaseModel):
    """Frozen runtime client selection config for Full-mode pipeline runs."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    backend_name: str = Field(default="reasoner-runtime", min_length=1)
    config_version: str = Field(default="runtime_backend_config.v1", min_length=1)
    provider: str | None = None
    model: str | None = None
    fallback_backend: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config_version(self) -> "RuntimeBackendConfig":
        if self.config_version not in _ALLOWED_CONFIG_VERSIONS:
            raise ValueError(
                f"unsupported runtime backend config_version: {self.config_version}"
            )
        return self


ReasonerClientFactory = Callable[[RuntimeBackendConfig], ReasonerRuntimeClient]

_ENV_BACKEND_NAME = "SUBSYSTEM_NEWS_REASONER_BACKEND"
_ENV_CONFIG_VERSION = "SUBSYSTEM_NEWS_REASONER_CONFIG_VERSION"
_ENV_PROVIDER = "SUBSYSTEM_NEWS_REASONER_PROVIDER"
_ENV_MODEL = "SUBSYSTEM_NEWS_REASONER_MODEL"
_ENV_FALLBACK_BACKEND = "SUBSYSTEM_NEWS_REASONER_FALLBACK_BACKEND"


def load_runtime_backend_config(
    env: Mapping[str, str] | None = None,
) -> RuntimeBackendConfig:
    """Build backend selection config from approved environment keys only."""

    source = os.environ if env is None else env
    return RuntimeBackendConfig(
        backend_name=_required_env_value(
            source,
            _ENV_BACKEND_NAME,
            default=_DEFAULT_BACKEND_NAME,
        ),
        config_version=_required_env_value(
            source,
            _ENV_CONFIG_VERSION,
            default=_DEFAULT_CONFIG_VERSION,
        ),
        provider=_optional_env_value(source, _ENV_PROVIDER),
        model=_optional_env_value(source, _ENV_MODEL),
        fallback_backend=_optional_env_value(source, _ENV_FALLBACK_BACKEND),
    )


def resolve_reasoner_client(
    config: RuntimeBackendConfig,
    factories: Mapping[str, ReasonerClientFactory] | None = None,
) -> ReasonerRuntimeClient:
    """Resolve a reasoner-runtime client from a backend registry."""

    registry: dict[str, ReasonerClientFactory] = {
        _DEFAULT_BACKEND_NAME: lambda _: DefaultReasonerRuntimeClient(),
    }
    if factories is not None:
        registry.update(factories)

    _validate_backend_config_for_registry(config, registry)
    factory = registry.get(config.backend_name)
    if factory is None:
        raise ContractViolationError(
            f"unknown reasoner runtime backend: {config.backend_name}"
        )
    return factory(config)


def _validate_backend_config_for_registry(
    config: RuntimeBackendConfig,
    registry: Mapping[str, ReasonerClientFactory],
) -> None:
    if config.config_version not in _ALLOWED_CONFIG_VERSIONS:
        raise ContractViolationError(
            f"unsupported runtime backend config_version: {config.config_version}"
        )
    if config.fallback_backend is not None and config.fallback_backend not in registry:
        raise ContractViolationError(
            f"unknown fallback reasoner runtime backend: {config.fallback_backend}"
        )


def _required_env_value(
    env: Mapping[str, str],
    key: str,
    *,
    default: str,
) -> str:
    if key not in env:
        return default
    return env[key]


def _optional_env_value(env: Mapping[str, str], key: str) -> str | None:
    if key not in env:
        return None
    value = env[key].strip()
    if not value:
        return None
    return value


__all__ = [
    "ReasonerClientFactory",
    "RuntimeBackendConfig",
    "load_runtime_backend_config",
    "resolve_reasoner_client",
]
