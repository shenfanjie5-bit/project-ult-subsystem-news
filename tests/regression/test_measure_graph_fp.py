from __future__ import annotations

from pathlib import Path

import pytest

from scripts.measure_graph_fp import main


def test_measure_graph_fp_requires_existing_fixture_directories(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="fixture directory"):
        main(
            [
                "--positive",
                str(tmp_path / "missing-positive"),
                "--negative",
                str(tmp_path / "missing-negative"),
            ]
        )


def test_measure_graph_fp_rejects_empty_fixture_sets(tmp_path: Path) -> None:
    positive = tmp_path / "positive"
    negative = tmp_path / "negative"
    positive.mkdir()
    negative.mkdir()

    with pytest.raises(ValueError, match="graph_positive"):
        main(["--positive", str(positive), "--negative", str(negative)])


def test_measure_graph_fp_enforces_reviewed_negative_minimum(tmp_path: Path) -> None:
    positive = tmp_path / "positive"
    negative = tmp_path / "negative"
    positive.mkdir()
    negative.mkdir()
    (positive / "cases.json").write_text('[{"name": "positive"}]', encoding="utf-8")
    (negative / "cases.json").write_text('[{"name": "negative"}]', encoding="utf-8")

    with pytest.raises(ValueError, match="at least 30 reviewed cases"):
        main(["--positive", str(positive), "--negative", str(negative)])
