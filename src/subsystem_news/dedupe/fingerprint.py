"""Deterministic article fingerprint helpers for dedupe clustering."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

from subsystem_news.contracts.article import NewsArticleArtifact

_TERM_RE = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def normalized_terms(text: str) -> tuple[str, ...]:
    """Return stable lowercase terms from already-normalized article text."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(_TERM_RE.findall(normalized))


def shingle_set(tokens: Sequence[str], *, size: int = 5) -> frozenset[str]:
    """Return ordered token shingles with a deterministic short-text fallback."""

    if size < 1:
        raise ValueError("shingle size must be positive")
    if not tokens:
        return frozenset()
    if len(tokens) < size:
        return frozenset({" ".join(tokens)})
    return frozenset(
        " ".join(tokens[index : index + size])
        for index in range(0, len(tokens) - size + 1)
    )


def article_fingerprint(
    artifact: NewsArticleArtifact,
    *,
    shingle_size: int = 5,
    max_tokens: int = 512,
) -> str:
    """Build a stable fingerprint from artifact title and clean body text only."""

    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    tokens = normalized_terms(f"{artifact.title}\n{artifact.body_text}")[:max_tokens]
    shingles = shingle_set(tokens, size=shingle_size)
    seed = "\n".join(sorted(shingles))
    digest = hashlib.sha256(f"dedupe:v1\n{seed}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
