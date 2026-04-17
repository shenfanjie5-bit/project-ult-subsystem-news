"""Local JSON artifact store for normalized news articles."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.errors import ContractViolationError


_NORMALIZATION_METADATA_ATTR = "_normalization_metadata"


class ArticleArtifactMetadata(BaseModel):
    """Sidecar metadata that is outside the immutable artifact contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str
    content_hash: str
    body_text_source: Literal["raw_body", "raw_html", "summary"]
    text_quality: Literal["full_text", "summary_only"]

    @model_validator(mode="after")
    def validate_text_quality_matches_body_source(self) -> "ArticleArtifactMetadata":
        expected_quality = "summary_only" if self.body_text_source == "summary" else "full_text"
        if self.text_quality != expected_quality:
            raise ValueError("text_quality must match body_text_source")
        return self


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

    def metadata_path_for(self, article_id: str) -> Path:
        return self.root / f"{self._safe_article_id(article_id)}.metadata.json"

    def save(self, artifact: NewsArticleArtifact) -> Path:
        path = self.path_for(artifact.article_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = artifact.model_dump_json(indent=2) + "\n"
        if path.exists():
            self._require_idempotent_artifact(path, artifact)

        metadata = self._metadata_from_artifact(artifact)
        if metadata is not None:
            self._require_idempotent_metadata(metadata)

        if not path.exists():
            self._atomic_write(path, payload)

        if metadata is not None:
            self._save_metadata(metadata)
        return path

    def load(self, article_id: str) -> NewsArticleArtifact:
        path = self.path_for(article_id)
        try:
            return NewsArticleArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ContractViolationError("stored article artifact violates NewsArticleArtifact") from exc

    def load_metadata(self, article_id: str) -> ArticleArtifactMetadata:
        path = self.metadata_path_for(article_id)
        try:
            return ArticleArtifactMetadata.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ContractViolationError("stored article metadata violates ArticleArtifactMetadata") from exc

    def exists(self, article_id: str) -> bool:
        return self.path_for(article_id).exists()

    def _safe_article_id(self, article_id: str) -> str:
        self.path_for(article_id)
        return article_id

    def _require_idempotent_artifact(
        self,
        path: Path,
        artifact: NewsArticleArtifact,
    ) -> None:
        try:
            existing = NewsArticleArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ContractViolationError(
                "existing stored article artifact violates NewsArticleArtifact"
            ) from exc

        if existing == artifact:
            return
        if existing.content_hash != artifact.content_hash:
            raise ContractViolationError(
                "refusing to overwrite existing article artifact with different content_hash"
            )
        raise ContractViolationError("refusing to overwrite different article artifact for article_id")

    def _metadata_from_artifact(
        self,
        artifact: NewsArticleArtifact,
    ) -> ArticleArtifactMetadata | None:
        payload = getattr(artifact, _NORMALIZATION_METADATA_ATTR, None)
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ContractViolationError("article normalization metadata must be a dict")

        try:
            return ArticleArtifactMetadata.model_validate(
                {
                    "article_id": artifact.article_id,
                    "content_hash": artifact.content_hash,
                    "body_text_source": payload["body_text_source"],
                    "text_quality": payload["text_quality"],
                }
            )
        except (KeyError, ValidationError, ValueError) as exc:
            raise ContractViolationError(
                "article normalization metadata violates ArticleArtifactMetadata"
            ) from exc

    def _save_metadata(self, metadata: ArticleArtifactMetadata) -> None:
        path = self.metadata_path_for(metadata.article_id)
        payload = metadata.model_dump_json(indent=2) + "\n"
        if self._require_idempotent_metadata(metadata):
            return
        self._atomic_write(path, payload)

    def _require_idempotent_metadata(self, metadata: ArticleArtifactMetadata) -> bool:
        path = self.metadata_path_for(metadata.article_id)
        if not path.exists():
            return False
        try:
            existing = ArticleArtifactMetadata.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ContractViolationError(
                "existing stored article metadata violates ArticleArtifactMetadata"
            ) from exc
        if existing != metadata:
            raise ContractViolationError(
                "refusing to overwrite different article metadata for article_id"
            )
        return True

    def _atomic_write(self, path: Path, payload: str) -> None:
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

            if path.exists():
                raise ContractViolationError("artifact path appeared during atomic write")
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
