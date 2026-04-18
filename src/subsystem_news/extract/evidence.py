"""Evidence span coercion and article-bound validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.errors import ContractViolationError, EvidenceMissingError


def coerce_evidence_spans(
    article: NewsArticleArtifact,
    raw_spans: Sequence[Mapping[str, object]],
) -> list[EvidenceSpan]:
    """Parse raw runtime span mappings and validate them against the article."""

    if not raw_spans:
        raise EvidenceMissingError("fact candidate requires at least one evidence span")

    spans: list[EvidenceSpan] = []
    for raw_span in raw_spans:
        try:
            spans.append(EvidenceSpan.model_validate(raw_span))
        except ValidationError as exc:
            raise ContractViolationError("runtime evidence span violates contract") from exc
    return validate_evidence_spans(article, spans)


def validate_evidence_spans(
    article: NewsArticleArtifact,
    spans: Sequence[EvidenceSpan],
) -> list[EvidenceSpan]:
    """Ensure evidence spans are non-empty exact title/body slices."""

    if not spans:
        raise EvidenceMissingError("fact candidate requires at least one evidence span")

    validated: list[EvidenceSpan] = []
    for span in spans:
        if span.article_id != article.article_id:
            raise ContractViolationError("evidence span article_id must match article")
        if span.start_char < 0 or span.end_char < 0:
            raise ContractViolationError("evidence span offsets must be non-negative")

        source_text = _source_text(article, span.locator)
        if span.end_char > len(source_text):
            raise ContractViolationError("evidence span exceeds article text bounds")
        if source_text[span.start_char : span.end_char] != span.quote:
            raise ContractViolationError("evidence span quote does not match article text")
        validated.append(span)

    return validated


def _source_text(article: NewsArticleArtifact, locator: str) -> str:
    if locator == "title":
        return article.title
    if locator == "body":
        return article.body_text
    raise ContractViolationError(f"unsupported evidence locator: {locator}")
