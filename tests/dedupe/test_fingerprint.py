from __future__ import annotations

import pytest

from subsystem_news.dedupe.fingerprint import (
    article_fingerprint,
    normalized_terms,
    shingle_set,
)

from .helpers import make_artifact


def test_normalized_terms_casefolds_ascii_and_keeps_cjk_terms() -> None:
    assert normalized_terms("ACME, Battery-2026 宁德时代") == (
        "acme",
        "battery",
        "2026",
        "宁",
        "德",
        "时",
        "代",
    )


def test_shingle_set_uses_short_text_fallback() -> None:
    assert shingle_set(("alpha", "beta"), size=5) == frozenset({"alpha beta"})
    assert shingle_set(("a", "b", "c"), size=2) == frozenset({"a b", "b c"})


def test_shingle_set_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError, match="positive"):
        shingle_set(("alpha",), size=0)


def test_article_fingerprint_is_stable_and_body_sensitive() -> None:
    artifact = make_artifact()
    changed = artifact.model_copy(update={"body_text": f"{artifact.body_text} Updated."})

    assert article_fingerprint(artifact) == article_fingerprint(artifact)
    assert article_fingerprint(artifact) != article_fingerprint(changed)


def test_article_fingerprint_uses_artifact_title_and_body_only() -> None:
    artifact = make_artifact()
    same_text_different_source = artifact.model_copy(
        update={
            "article_id": "article-b",
            "source_id": "source-b",
            "content_hash": "sha256:other-content",
            "article_fingerprint": "sha256:provider-seed",
        }
    )

    assert article_fingerprint(artifact) == article_fingerprint(same_text_different_source)
