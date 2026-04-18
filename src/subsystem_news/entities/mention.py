"""Deterministic mention detection for normalized news artifacts."""

from __future__ import annotations

import re
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.source_reference import SourceReference


MentionLocator = Literal["title", "body"]


class Mention(BaseModel):
    """A located entity or theme mention in a normalized article."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str = Field(min_length=1)
    text: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    locator: MentionLocator
    type_hint: str = Field(min_length=1)
    context: str
    source_reference: SourceReference

    @model_validator(mode="after")
    def validate_offsets_and_text(self) -> "Mention":
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        if not self.text.strip():
            raise ValueError("text must be non-empty")
        return self


_STOCK_CODE_PATTERNS = (
    re.compile(
        r"(?<![A-Za-z0-9$])(?:NASDAQ|NYSE|HKEX|SSE|SZSE|SHSE):\s?[A-Z0-9]{1,8}"
        r"(?![A-Za-z0-9])"
    ),
    re.compile(r"(?<![A-Za-z0-9])\$[A-Z]{1,6}(?:\.[A-Z])?(?![A-Za-z0-9])"),
    re.compile(r"\b\d{6}\.(?:SH|SZ)\b"),
    re.compile(r"\b\d{4}\.HK\b"),
    re.compile(r"\b[A-Z]{1,5}\.(?:N|O|L|PA|TO|HK)\b"),
    re.compile(r"(?<=\()[A-Z]{1,5}(?=\))"),
)

_EN_COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,5}\s+"
    r"(?:Corp(?:oration)?|Inc(?:orporated)?|Ltd|Limited|LLC|PLC|AG|SA|SE|NV|Co)\.?\b"
)

_EN_INDUSTRY_NAME_PATTERN = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&.-]*\s+){1,5}"
    r"(?:Metals|Energy|Motors|Automotive|Semiconductors?|Pharma|Therapeutics|"
    r"Bank|Airlines|Mining|Steel|Power|Holdings|Capital)\b"
)

_STANDARD_ABBREVIATION_PATTERN = re.compile(r"\b[A-Z][A-Z0-9&]{1,6}\b")
_ABBREVIATION_STOPWORDS = {
    "AI",
    "API",
    "CEO",
    "CFO",
    "COO",
    "EU",
    "EV",
    "FDA",
    "GDP",
    "IPO",
    "SEC",
    "UK",
    "US",
    "USA",
}

_ZH_COMPANY_PATTERN = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{2,24}(?:股份有限公司|有限公司|集团股份有限公司|集团|控股)"
)
_ZH_SHORT_COMPANY_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{2,12}(?:时代|科技|能源|汽车|银行|证券|药业)"
)

_EN_TOPIC_PATTERNS = (
    re.compile(r"\blarge language models?\b", re.IGNORECASE),
    re.compile(r"\benergy storage systems?\b", re.IGNORECASE),
    re.compile(r"\bbattery modules?\b", re.IGNORECASE),
    re.compile(r"\bsupply contracts?\b", re.IGNORECASE),
    re.compile(r"\bnickel plants?\b", re.IGNORECASE),
    re.compile(r"\bAI chips?\b", re.IGNORECASE),
    re.compile(r"\belectric vehicles?\b", re.IGNORECASE),
)
_ZH_TOPIC_TERMS = (
    "新能源汽车",
    "储能系统",
    "人工智能",
    "大模型",
    "算力",
    "锂电池",
    "芯片",
)

_LOCATOR_ORDER = {"title": 0, "body": 1}
_TYPE_SPECIFICITY = {
    "stock_code": 50,
    "company": 40,
    "standard_abbreviation": 30,
    "product": 20,
    "market_theme": 10,
}


def _context_for(text: str, start_char: int, end_char: int, context_window: int) -> str:
    context_window = max(0, context_window)
    context_start = max(0, start_char - context_window)
    context_end = min(len(text), end_char + context_window)
    return text[context_start:context_end]


def _mention_from_span(
    article: NewsArticleArtifact,
    *,
    source_text: str,
    start_char: int,
    end_char: int,
    locator: MentionLocator,
    type_hint: str,
    context_window: int,
) -> Mention:
    mention_text = source_text[start_char:end_char]
    return Mention(
        article_id=article.article_id,
        text=mention_text,
        start_char=start_char,
        end_char=end_char,
        locator=locator,
        type_hint=type_hint,
        context=_context_for(source_text, start_char, end_char, context_window),
        source_reference=article.source_reference,
    )


def _append_regex_mentions(
    mentions: list[Mention],
    article: NewsArticleArtifact,
    *,
    source_text: str,
    locator: MentionLocator,
    pattern: re.Pattern[str],
    type_hint: str,
    context_window: int,
) -> None:
    for match in pattern.finditer(source_text):
        mentions.append(
            _mention_from_span(
                article,
                source_text=source_text,
                start_char=match.start(),
                end_char=match.end(),
                locator=locator,
                type_hint=type_hint,
                context_window=context_window,
            )
        )


def _append_term_mentions(
    mentions: list[Mention],
    article: NewsArticleArtifact,
    *,
    source_text: str,
    locator: MentionLocator,
    term: str,
    type_hint: str,
    context_window: int,
) -> None:
    start_at = 0
    while True:
        start_char = source_text.find(term, start_at)
        if start_char < 0:
            return
        end_char = start_char + len(term)
        mentions.append(
            _mention_from_span(
                article,
                source_text=source_text,
                start_char=start_char,
                end_char=end_char,
                locator=locator,
                type_hint=type_hint,
                context_window=context_window,
            )
        )
        start_at = end_char


def _append_abbreviation_mentions(
    mentions: list[Mention],
    article: NewsArticleArtifact,
    *,
    source_text: str,
    locator: MentionLocator,
    context_window: int,
) -> None:
    for match in _STANDARD_ABBREVIATION_PATTERN.finditer(source_text):
        text = match.group(0)
        if text in _ABBREVIATION_STOPWORDS:
            continue
        if text.isdigit():
            continue
        mentions.append(
            _mention_from_span(
                article,
                source_text=source_text,
                start_char=match.start(),
                end_char=match.end(),
                locator=locator,
                type_hint="standard_abbreviation",
                context_window=context_window,
            )
        )


def _detect_in_text(
    article: NewsArticleArtifact,
    *,
    source_text: str,
    locator: MentionLocator,
    context_window: int,
) -> list[Mention]:
    mentions: list[Mention] = []

    for pattern in _STOCK_CODE_PATTERNS:
        _append_regex_mentions(
            mentions,
            article,
            source_text=source_text,
            locator=locator,
            pattern=pattern,
            type_hint="stock_code",
            context_window=context_window,
        )

    for pattern in (
        _EN_COMPANY_SUFFIX_PATTERN,
        _EN_INDUSTRY_NAME_PATTERN,
        _ZH_COMPANY_PATTERN,
        _ZH_SHORT_COMPANY_PATTERN,
    ):
        _append_regex_mentions(
            mentions,
            article,
            source_text=source_text,
            locator=locator,
            pattern=pattern,
            type_hint="company",
            context_window=context_window,
        )

    _append_abbreviation_mentions(
        mentions,
        article,
        source_text=source_text,
        locator=locator,
        context_window=context_window,
    )

    for pattern in _EN_TOPIC_PATTERNS:
        _append_regex_mentions(
            mentions,
            article,
            source_text=source_text,
            locator=locator,
            pattern=pattern,
            type_hint="market_theme",
            context_window=context_window,
        )

    for term in _ZH_TOPIC_TERMS:
        _append_term_mentions(
            mentions,
            article,
            source_text=source_text,
            locator=locator,
            term=term,
            type_hint="market_theme",
            context_window=context_window,
        )

    return mentions


def detect_mentions(article: NewsArticleArtifact, *, context_window: int = 80) -> list[Mention]:
    """Detect deterministic mention candidates in article title and body text."""

    mentions: list[Mention] = []
    mentions.extend(
        _detect_in_text(
            article,
            source_text=article.title,
            locator="title",
            context_window=context_window,
        )
    )
    mentions.extend(
        _detect_in_text(
            article,
            source_text=article.body_text,
            locator="body",
            context_window=context_window,
        )
    )
    return dedupe_mentions(mentions)


def _sort_key(mention: Mention) -> tuple[str, int, int, int, str]:
    return (
        mention.article_id,
        _LOCATOR_ORDER[mention.locator],
        mention.start_char,
        mention.end_char,
        mention.text,
    )


def _specificity_key(mention: Mention) -> tuple[int, int, int]:
    return (
        mention.end_char - mention.start_char,
        _TYPE_SPECIFICITY.get(mention.type_hint, 0),
        -mention.start_char,
    )


def _overlaps(left: Mention, right: Mention) -> bool:
    if left.article_id != right.article_id or left.locator != right.locator:
        return False
    return max(left.start_char, right.start_char) < min(left.end_char, right.end_char)


def dedupe_mentions(mentions: Sequence[Mention]) -> list[Mention]:
    """Deduplicate mentions and prefer longer, more specific overlapping spans."""

    unique: dict[tuple[str, str, int, int, str], Mention] = {}
    for mention in mentions:
        key = (
            mention.article_id,
            mention.locator,
            mention.start_char,
            mention.end_char,
            mention.text,
        )
        existing = unique.get(key)
        if existing is None or _specificity_key(mention) > _specificity_key(existing):
            unique[key] = mention

    kept: list[Mention] = []
    for mention in sorted(unique.values(), key=_sort_key):
        conflict_indexes = [
            index for index, existing in enumerate(kept) if _overlaps(existing, mention)
        ]
        if not conflict_indexes:
            kept.append(mention)
            continue

        winner = max(
            [mention, *(kept[index] for index in conflict_indexes)],
            key=_specificity_key,
        )
        if winner == mention:
            kept = [
                existing
                for index, existing in enumerate(kept)
                if index not in set(conflict_indexes)
            ]
            kept.append(mention)

    return sorted(kept, key=_sort_key)
