from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from subsystem_news.errors import ContractViolationError
from subsystem_news.fixtures.catalog import FixtureSuite
from subsystem_news.fixtures.loader import load_fixture_suite, validate_fixture_suite


MANIFEST = Path("src/subsystem_news/fixtures/regression/manifest.json")


def test_regression_manifest_declares_required_categories_and_scale() -> None:
    suite = load_fixture_suite(MANIFEST)
    counts = Counter(case.category for case in suite.cases)

    assert set(counts) == {
        "single_source",
        "repost_cluster",
        "ambiguous_entity",
        "graph_positive",
        "ex1_only",
        "graph_negative",
    }
    assert counts["repost_cluster"] >= 10
    assert sum(len(case.article_ids) for case in suite.cases if case.category == "repost_cluster") >= 20
    assert counts["graph_negative"] >= 30
    assert all(case.version_pins for case in suite.cases)
    assert all(
        output.source_reference is not None and output.evidence_spans
        for case in suite.cases
        for output in case.expected_outputs
    )


def test_fixture_validator_rejects_evidence_quote_mismatch() -> None:
    suite = load_fixture_suite(MANIFEST)
    payload = suite.model_dump(mode="json")
    payload["cases"][0]["expected_outputs"][0]["evidence_spans"][0]["quote"] = (
        "not present in normalized artifact"
    )
    broken = FixtureSuite.model_validate(payload)

    with pytest.raises(ContractViolationError, match="evidence quote"):
        validate_fixture_suite(broken)


def test_focus_area_cases_are_fixed_in_regression_manifest() -> None:
    suite = load_fixture_suite(MANIFEST)
    single = next(case for case in suite.cases if case.case_id == "single-source-standard")
    ex2_outputs = [
        output for output in single.expected_outputs if output.export_contract == "Ex-2"
    ]
    ex1_only = next(case for case in suite.cases if case.category == "ex1_only")
    repost = [case for case in suite.cases if case.category == "repost_cluster"]

    assert {output.direction for output in ex2_outputs} == {"positive", "negative"}
    assert {entity.mention_text for output in ex2_outputs for entity in output.affected_entities} == {
        "Acme Corp",
        "Globex Inc",
    }
    assert all(output.export_contract == "Ex-1" for output in ex1_only.expected_outputs)
    assert all(
        sum(1 for output in case.expected_outputs if output.export_contract == "Ex-2") == 1
        for case in repost
    )
