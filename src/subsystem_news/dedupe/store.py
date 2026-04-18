"""Local JSON state store for dedupe article snapshots and clusters."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.errors import ContractViolationError


class DedupeStore:
    """Persist dedupe-local snapshots, clusters, and article-cluster indexes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.article_dir = root / "articles"
        self.cluster_dir = root / "clusters"
        self.trace_dir = root / "traces"
        self._index_path = root / "article_cluster_index.json"

    def save_article_snapshot(self, artifact: NewsArticleArtifact) -> Path:
        """Save an article snapshot without silently overwriting content drift."""

        path = self._article_path(artifact.article_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = artifact
        if path.exists():
            existing = self.load_article_snapshot(artifact.article_id)
            if existing == artifact:
                self._index_article_if_clustered(artifact)
                return path
            snapshot = self._compatible_article_snapshot(existing, artifact)
            if snapshot == existing:
                self._index_article_if_clustered(existing)
                return path

        self._write_json(path, snapshot.model_dump_json(indent=2) + "\n")
        self._index_article_if_clustered(snapshot)
        return path

    def load_article_snapshot(self, article_id: str) -> NewsArticleArtifact:
        path = self._article_path(article_id)
        try:
            return NewsArticleArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ContractViolationError(
                "stored dedupe article snapshot violates NewsArticleArtifact"
            ) from exc

    def save_cluster(self, cluster: NewsDedupeCluster) -> Path:
        """Save a cluster, permitting append-only member convergence."""

        path = self._cluster_path(cluster.cluster_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = self.load_cluster(cluster.cluster_id)
            if existing == cluster:
                self._index_cluster(cluster)
                return path
            self._validate_cluster_update(existing, cluster)

        self._validate_index_update(cluster)
        self._write_json(path, cluster.model_dump_json(indent=2) + "\n")
        self._index_cluster(cluster)
        return path

    def load_cluster(self, cluster_id: str) -> NewsDedupeCluster:
        path = self._cluster_path(cluster_id)
        try:
            return NewsDedupeCluster.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ContractViolationError("stored dedupe cluster violates NewsDedupeCluster") from exc

    def list_clusters(self) -> list[NewsDedupeCluster]:
        if not self.cluster_dir.exists():
            return []
        return [
            self.load_cluster(path.stem)
            for path in sorted(self.cluster_dir.glob("*.json"))
        ]

    def cluster_for_article(self, article_id: str) -> NewsDedupeCluster | None:
        self._safe_id(article_id, "article_id")
        index = self._load_index()
        cluster_id = index.get(article_id)
        if cluster_id is not None:
            return self.load_cluster(cluster_id)
        for cluster in self.list_clusters():
            if article_id in cluster.member_article_ids:
                return cluster
        return None

    def iter_article_snapshots(self) -> Iterator[NewsArticleArtifact]:
        if not self.article_dir.exists():
            return
        for path in sorted(self.article_dir.glob("*.json")):
            yield self.load_article_snapshot(path.stem)

    def _article_path(self, article_id: str) -> Path:
        return self.article_dir / f"{self._safe_id(article_id, 'article_id')}.json"

    def _cluster_path(self, cluster_id: str) -> Path:
        return self.cluster_dir / f"{self._safe_id(cluster_id, 'cluster_id')}.json"

    def _safe_id(self, value: str, field_name: str) -> str:
        if not value or value.strip() != value:
            raise ContractViolationError(f"{field_name} must be non-empty without edge whitespace")
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ContractViolationError(f"{field_name} must be safe for local dedupe storage")
        return value

    def _compatible_article_snapshot(
        self,
        existing: NewsArticleArtifact,
        incoming: NewsArticleArtifact,
    ) -> NewsArticleArtifact:
        if existing.content_hash != incoming.content_hash:
            raise ContractViolationError(
                "refusing to overwrite existing article snapshot with different content_hash"
            )
        existing_without_cluster = existing.model_copy(update={"cluster_id": None})
        incoming_without_cluster = incoming.model_copy(update={"cluster_id": None})
        if existing_without_cluster != incoming_without_cluster:
            raise ContractViolationError(
                "refusing to overwrite different article snapshot for article_id"
            )
        if existing.cluster_id is not None and incoming.cluster_id is not None:
            if existing.cluster_id != incoming.cluster_id:
                raise ContractViolationError(
                    "refusing to move article snapshot between dedupe clusters"
                )
        if incoming.cluster_id is not None and existing.cluster_id is None:
            return incoming
        return existing

    def _validate_cluster_update(
        self,
        existing: NewsDedupeCluster,
        incoming: NewsDedupeCluster,
    ) -> None:
        if existing.fingerprint_family != incoming.fingerprint_family:
            raise ContractViolationError(
                "refusing to overwrite cluster with different fingerprint_family"
            )
        existing_members = set(existing.member_article_ids)
        incoming_members = set(incoming.member_article_ids)
        if not existing_members.issubset(incoming_members):
            raise ContractViolationError("refusing to remove members from existing cluster")

    def _validate_index_update(self, cluster: NewsDedupeCluster) -> None:
        index = self._load_index()
        for article_id in cluster.member_article_ids:
            mapped_cluster_id = index.get(article_id)
            if mapped_cluster_id is not None and mapped_cluster_id != cluster.cluster_id:
                raise ContractViolationError(
                    "article is already indexed to a different dedupe cluster"
                )

    def _index_article_if_clustered(self, artifact: NewsArticleArtifact) -> None:
        if artifact.cluster_id is None:
            return
        if not self._cluster_path(artifact.cluster_id).exists():
            return
        index = self._load_index()
        existing = index.get(artifact.article_id)
        if existing is not None and existing != artifact.cluster_id:
            raise ContractViolationError(
                "article is already indexed to a different dedupe cluster"
            )
        index[artifact.article_id] = artifact.cluster_id
        self._save_index(index)

    def _index_cluster(self, cluster: NewsDedupeCluster) -> None:
        index = self._load_index()
        for article_id in cluster.member_article_ids:
            existing = index.get(article_id)
            if existing is not None and existing != cluster.cluster_id:
                raise ContractViolationError(
                    "article is already indexed to a different dedupe cluster"
                )
            index[article_id] = cluster.cluster_id
        self._save_index(index)

    def _load_index(self) -> dict[str, str]:
        if not self._index_path.exists():
            return {}
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractViolationError("dedupe article-cluster index is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ContractViolationError("dedupe article-cluster index must be a JSON object")
        index: dict[str, str] = {}
        for article_id, cluster_id in payload.items():
            if not isinstance(article_id, str) or not isinstance(cluster_id, str):
                raise ContractViolationError("dedupe article-cluster index entries must be strings")
            index[self._safe_id(article_id, "article_id")] = self._safe_id(
                cluster_id,
                "cluster_id",
            )
        return index

    def _save_index(self, index: dict[str, str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(index, indent=2, sort_keys=True) + "\n"
        self._write_json(self._index_path, payload)

    def _write_json(self, path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=path.parent,
                encoding="utf-8",
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
