"""Stable hash inputs used before true dedupe clustering."""

from __future__ import annotations

import hashlib
import re

from subsystem_news.normalize.text_clean import clean_text, normalize_title


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])\s+")


def content_hash(text: str) -> str:
    """Return a stable SHA-256 hash for the supplied article text."""

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _sentences(text: str) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []
    return [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(normalized) if part.strip()]


def fingerprint_seed(title: str, body: str, *, max_sentences: int = 8) -> str:
    """Hash the normalized title and early article sentences for later dedupe."""

    normalized_title = normalize_title(title)
    selected_sentences = _sentences(body)[:max_sentences]
    seed_text = "\n".join([normalized_title, *selected_sentences])
    return content_hash(seed_text)
