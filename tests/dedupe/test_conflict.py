from __future__ import annotations

import json
from pathlib import Path

from subsystem_news.dedupe.cluster import build_cluster
from subsystem_news.dedupe.conflict import detect_conflicts, write_conflict_trace

from .helpers import load_group_fixture, make_artifact


def test_detect_conflicts_records_trace_only_conflicts() -> None:
    members = load_group_fixture("conflict_group.json")

    conflicts = detect_conflicts(members)
    conflict_types = {conflict.conflict_type for conflict in conflicts}

    assert "published_at_conflict" in conflict_types
    assert "source_reference_drift" in conflict_types
    assert conflicts


def test_write_conflict_trace_writes_json_when_conflicts_exist(tmp_path: Path) -> None:
    members = load_group_fixture("conflict_group.json")
    cluster = build_cluster(members, fingerprint_family="sha256:conflict-family", confidence=0.88)
    conflicts = detect_conflicts(members)

    path = write_conflict_trace(cluster, conflicts, tmp_path)

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["cluster_id"] == cluster.cluster_id
    assert len(payload["conflicts"]) == len(conflicts)


def test_write_conflict_trace_returns_none_without_conflicts(tmp_path: Path) -> None:
    artifact = make_artifact()
    cluster = build_cluster([artifact], fingerprint_family="sha256:single", confidence=1.0)

    assert write_conflict_trace(cluster, [], tmp_path) is None
    assert not list(tmp_path.iterdir())
