"""Text cleanup helpers for normalized article artifacts."""

from __future__ import annotations

import html
import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _drop_control_chars(text: str) -> str:
    kept: list[str] = []
    for char in text:
        if char in "\t\n\r":
            kept.append(" ")
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            continue
        kept.append(char)
    return "".join(kept)


def clean_text(text: str) -> str:
    """Normalize article text without removing meaningful CJK or Latin content."""

    unescaped = html.unescape(text).replace("\xa0", " ")
    without_controls = _drop_control_chars(unescaped)
    collapsed = _WHITESPACE_RE.sub(" ", without_controls)
    return collapsed.strip(" \t\r\n\ufeff")


def normalize_title(title: str | None) -> str:
    """Return a cleaned title string, using an empty string for missing titles."""

    if title is None:
        return ""
    return clean_text(title)


def detect_language(title: str, body: str, source_language: str | None = None) -> str:
    """Infer a coarse language tag, preferring approved-source metadata."""

    if source_language is not None:
        normalized = clean_text(source_language).lower()
        if normalized:
            return normalized

    combined = f"{title} {body}"
    cjk_count = len(_CJK_RE.findall(combined))
    latin_count = len(_LATIN_RE.findall(combined))

    if cjk_count and cjk_count >= latin_count:
        return "zh"
    if latin_count:
        return "en"
    if cjk_count:
        return "zh"
    return "unknown"
