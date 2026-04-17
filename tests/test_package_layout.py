"""Package layout and scaffold contract tests."""

from __future__ import annotations

import importlib

from subsystem_news.errors import (
    ContractViolationError,
    EntityResolutionError,
    EvidenceMissingError,
    SourceNotApprovedError,
    SubsystemNewsError,
)


SUBMODULES = (
    "sources",
    "normalize",
    "dedupe",
    "entities",
    "extract",
    "signals",
    "graph",
    "runtime",
    "fixtures",
)

ERROR_TYPES = (
    SubsystemNewsError,
    SourceNotApprovedError,
    EvidenceMissingError,
    EntityResolutionError,
    ContractViolationError,
)


def test_all_submodules_importable() -> None:
    for submodule in SUBMODULES:
        imported = importlib.import_module(f"subsystem_news.{submodule}")
        assert imported.__name__ == f"subsystem_news.{submodule}"


def test_errors_have_codes() -> None:
    for error_type in ERROR_TYPES:
        err = error_type("example")
        assert isinstance(err, SubsystemNewsError)
        assert isinstance(err.code, str)
        assert err.code
