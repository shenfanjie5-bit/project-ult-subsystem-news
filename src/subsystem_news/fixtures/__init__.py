"""Fixtures, labeled samples, and regression sample assets."""

from subsystem_news.fixtures.catalog import (
    ExpectedCandidateSummary,
    FixtureCase,
    FixtureSuite,
    RegressionReport,
    RegressionThresholds,
)
from subsystem_news.fixtures.loader import load_fixture_suite, validate_fixture_suite
from subsystem_news.fixtures.metrics import (
    compute_dedupe_precision,
    compute_evidence_coverage,
    compute_ex2_contract_completeness,
    compute_ex3_false_positive_rate,
    compute_unresolved_explicitness,
)
from subsystem_news.fixtures.runner import run_regression_suite

__all__ = [
    "ExpectedCandidateSummary",
    "FixtureCase",
    "FixtureSuite",
    "RegressionReport",
    "RegressionThresholds",
    "compute_dedupe_precision",
    "compute_evidence_coverage",
    "compute_ex2_contract_completeness",
    "compute_ex3_false_positive_rate",
    "compute_unresolved_explicitness",
    "load_fixture_suite",
    "run_regression_suite",
    "validate_fixture_suite",
]
