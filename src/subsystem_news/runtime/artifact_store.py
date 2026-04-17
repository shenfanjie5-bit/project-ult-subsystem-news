"""Local JSON artifact store for normalized news articles."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.errors import ContractViolationError


class ArtifactStore:
    """Persist normalized article artifacts as deterministic JSON files."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, article_id: str) -> Path:
        if not article_id or article_id.strip() != article_id:
            raise ContractViolationError("article_id must be non-empty without edge whitespace")
        if "/" in article_id or "\\" in article_id or article_id in {".", ".."}:
            raise ContractViolationError("article_id must be safe for local artifact storage")
        return self.root / f"{article_id}.json"

    def save(self, artifact: NewsArticleArtifact) -> Path:
        path = self.path_for(artifact.article_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return path

    def load(self, article_id: str) -> NewsArticleArtifact:
        path = self.path_for(article_id)
        try:
            return NewsArticleArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ContractViolationError("stored article artifact violates NewsArticleArtifact") from exc

    def exists(self, article_id: str) -> bool:
        return self.path_for(article_id).exists()
