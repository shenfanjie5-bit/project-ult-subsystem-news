from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from subsystem_news.contracts.candidates import NewsSignalCandidate
from subsystem_news.errors import EvidenceMissingError


GOLDEN_ROOT = Path(__file__).parent / "golden" / "ex2"

FROZEN_EX2_FIELDS = frozenset(
    {
        "candidate_id",
        "article_id",
        "cluster_id",
        "source_reference",
        "signal_type",
        "direction",
        "magnitude",
        "affected_entities",
        "impact_scope",
        "time_horizon",
        "rationale",
        "confidence",
        "evidence_spans",
        "export_contract",
    }
)

STREAM_REQUIRED_FIELDS = frozenset(
    {
        "signal_type",
        "direction",
        "magnitude",
        "affected_entities",
        "impact_scope",
        "time_horizon",
        "source_reference",
        "evidence_spans",
        "export_contract",
    }
)


def _golden_paths() -> list[Path]:
    return sorted(GOLDEN_ROOT.glob("*.json"))


def _load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_ex2_model_field_set_is_frozen() -> None:
    assert frozenset(NewsSignalCandidate.model_fields) == FROZEN_EX2_FIELDS
    assert STREAM_REQUIRED_FIELDS <= FROZEN_EX2_FIELDS


def test_golden_ex2_samples_cover_required_contract_variants() -> None:
    candidates = [
        NewsSignalCandidate.model_validate_json(path.read_text(encoding="utf-8"))
        for path in _golden_paths()
    ]

    assert len(candidates) == 6
    assert {candidate.direction for candidate in candidates} == {
        "positive",
        "negative",
        "neutral",
        "mixed",
    }
    assert {type(candidate.magnitude) for candidate in candidates} == {str, float}
    assert {
        candidate.impact_scope for candidate in candidates
    } >= {"company", "sector", "supply_chain", "market_theme"}


@pytest.mark.parametrize("path", _golden_paths(), ids=lambda path: path.stem)
def test_golden_ex2_samples_validate_and_round_trip_without_field_loss(
    path: Path,
) -> None:
    candidate = NewsSignalCandidate.model_validate_json(path.read_text(encoding="utf-8"))
    dumped = json.loads(candidate.model_dump_json())
    restored = NewsSignalCandidate.model_validate_json(candidate.model_dump_json())

    assert candidate.export_contract == "Ex-2"
    assert frozenset(dumped) == FROZEN_EX2_FIELDS
    assert STREAM_REQUIRED_FIELDS <= frozenset(dumped)
    assert restored == candidate


@pytest.mark.parametrize(
    "field",
    ["source_reference", "evidence_spans"],
)
def test_golden_ex2_required_source_and_evidence_fields_are_still_required(
    field: str,
) -> None:
    payload = _load_payload(_golden_paths()[0])
    del payload[field]

    with pytest.raises((ValidationError, EvidenceMissingError)):
        NewsSignalCandidate.model_validate(payload)


def test_golden_ex2_empty_evidence_is_rejected_by_contract_guard() -> None:
    payload = _load_payload(_golden_paths()[0])
    payload["evidence_spans"] = []

    with pytest.raises(EvidenceMissingError):
        NewsSignalCandidate.model_validate(payload)
