"""Source discovery and raw fetch DTOs.

The source layer owns only traceable article references and raw payloads. It
does not normalize title, body, time, entities, or downstream candidates.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.contracts import NewsSourceConfig, SourceReference
from subsystem_news.errors import ContractViolationError


def _json_ready(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def raw_content_hash(payload: Mapping[str, object]) -> str:
    """Build a stable hash for raw source payload fields."""

    encoded = json.dumps(
        _json_ready(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def trace_id_for(source_id: str, content_hash: str, fetched_at: datetime) -> str:
    """Build a deterministic trace id from source, payload hash, and fetch time."""

    seed = f"{source_id}\n{content_hash}\n{fetched_at.isoformat()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"fetch-{digest[:24]}"


class NewsArticleRef(BaseModel):
    """Traceable reference discovered from an approved source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    source_reference: SourceReference
    url: str | None = None
    provider_key: str | None = Field(default=None, min_length=1)
    title_hint: str | None = None
    published_at_hint: datetime | None = None
    cursor: str | None = None

    @model_validator(mode="before")
    @classmethod
    def fill_locator_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        source_reference = data.get("source_reference")
        if source_reference is None:
            return data

        if isinstance(source_reference, SourceReference):
            reference_payload = source_reference.model_dump(mode="json")
        elif isinstance(source_reference, dict):
            reference_payload = source_reference
        else:
            return data

        filled = dict(data)
        if filled.get("url") is None and reference_payload.get("url") is not None:
            filled["url"] = str(reference_payload["url"])
        if filled.get("provider_key") is None and reference_payload.get("provider_key") is not None:
            filled["provider_key"] = reference_payload["provider_key"]
        return filled

    @model_validator(mode="after")
    def validate_source_reference_matches_source_id(self) -> "NewsArticleRef":
        if self.source_reference.source_id != self.source_id:
            raise ValueError("source_reference.source_id must match source_id")
        if self.url is None and self.provider_key is None:
            raise ValueError("news article reference requires url or provider_key")
        return self


def same_article_ref(left: NewsArticleRef, right: NewsArticleRef) -> bool:
    """Return whether two source refs identify the same article within one source."""

    if left.source_id != right.source_id:
        return False
    if left.source_reference == right.source_reference:
        return True
    if (
        left.provider_key is not None
        and right.provider_key is not None
        and left.provider_key == right.provider_key
    ):
        return True
    return left.url is not None and right.url is not None and left.url == right.url


def validate_response_url_within_source(
    response_url: str,
    source: NewsSourceConfig,
    *,
    adapter_name: str,
) -> None:
    """Reject redirects whose final URL leaves the approved source endpoint."""

    if _normalized_external_url(response_url) != _normalized_external_url(str(source.base_url)):
        raise ContractViolationError(
            f"{adapter_name} redirect target must match approved base_url"
        )


def _normalized_external_url(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


class RawArticleFetch(BaseModel):
    """Raw article payload after source policy checks and body fetch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: NewsArticleRef
    source: NewsSourceConfig
    raw_title: str | None = None
    raw_body: str | None = None
    raw_html: str | None = None
    summary: str | None = None
    published_at_raw: str | None = None
    author_or_channel: str | None = None
    fetched_at: datetime
    content_hash: str
    trace_id: str

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_payload(cls, data: object) -> object:
        """Accept pre-source-module raw fixtures without keeping legacy fields."""

        if not isinstance(data, dict) or "ref" in data or "source" in data:
            return data

        source_reference = data.get("source_reference")
        if source_reference is None:
            return data

        reference = SourceReference.model_validate(source_reference)
        source_id = data.get("source_id") or reference.source_id
        url = str(reference.url) if reference.url is not None else None
        source = {
            "source_id": source_id,
            "display_name": str(source_id),
            "access_mode": "rss",
            "base_url": url or "https://example.invalid/",
            "approved": True,
            "reliability_tier": data.get("reliability_tier"),
            "license_tag": data.get("license_tag"),
            "language": data.get("source_language"),
            "credential_ref": None,
        }
        raw_title = data.get("raw_title") or data.get("title")
        published_at_raw = data.get("published_at_raw") or data.get("published_at")
        fetched_at = data.get("fetched_at")
        ref = {
            "source_id": source_id,
            "source_reference": reference,
            "url": url,
            "provider_key": reference.provider_key,
            "title_hint": raw_title,
            "cursor": reference.provider_key or url,
        }
        migrated = {
            "ref": ref,
            "source": source,
            "raw_title": raw_title,
            "raw_body": data.get("raw_body"),
            "raw_html": data.get("raw_html"),
            "summary": data.get("summary"),
            "published_at_raw": published_at_raw,
            "author_or_channel": data.get("author_or_channel"),
            "fetched_at": fetched_at,
        }
        migrated["content_hash"] = data.get("content_hash") or raw_content_hash(
            {
                "source_reference": reference,
                "raw_title": raw_title,
                "raw_body": migrated["raw_body"],
                "raw_html": migrated["raw_html"],
                "summary": migrated["summary"],
                "published_at_raw": published_at_raw,
                "author_or_channel": migrated["author_or_channel"],
            }
        )
        parsed_fetched_at = (
            fetched_at
            if isinstance(fetched_at, datetime)
            else datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        )
        migrated["trace_id"] = data.get("trace_id") or trace_id_for(
            str(source_id),
            str(migrated["content_hash"]),
            parsed_fetched_at,
        )
        return migrated

    @model_validator(mode="after")
    def validate_ref_and_source_match(self) -> "RawArticleFetch":
        if self.source.source_id != self.ref.source_id:
            raise ValueError("source.source_id must match ref.source_id")
        return self

    @property
    def source_reference(self) -> SourceReference:
        """Compatibility accessor for downstream normalization."""

        return self.ref.source_reference

    @property
    def source_id(self) -> str:
        """Compatibility accessor for downstream normalization."""

        return self.ref.source_id

    @property
    def title(self) -> str | None:
        """Raw title value selected by sources, not a normalized title."""

        return self.raw_title or self.ref.title_hint

    @property
    def published_at(self) -> str | datetime | None:
        """Raw timestamp value selected by sources, not a normalized datetime."""

        return self.published_at_raw or self.ref.published_at_hint

    @property
    def source_language(self) -> str | None:
        """Compatibility accessor for the source-level language hint."""

        return self.source.language

    @property
    def license_tag(self) -> str:
        """Compatibility accessor for downstream artifact construction."""

        return self.source.license_tag

    @property
    def reliability_tier(self) -> str:
        """Compatibility accessor for downstream artifact construction."""

        return self.source.reliability_tier


class FetchTrace(BaseModel):
    """Persisted trace metadata for a raw fetch, excluding article body text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_reference: SourceReference
    url: str | None = None
    provider_key: str | None = None
    content_hash: str = Field(min_length=1)
    fetched_at: datetime
    error_code: str | None = None


class HttpResponse(BaseModel):
    """Minimal HTTP response shape used by source adapters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    status_code: int
    text: str
    headers: Mapping[str, str]


class HttpTransport(Protocol):
    """HTTP transport protocol for fixture-only source tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Fetch a URL and return decoded text."""


class UrllibHttpTransport:
    """Standard-library HTTP transport for approved source adapters."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        request = Request(url, headers=dict(headers or {}))
        with urlopen(request) as response:  # noqa: S310 - approved source URLs only.
            body = response.read()
            response_headers = dict(response.headers.items())
            charset = response.headers.get_content_charset() or "utf-8"
            text = body.decode(charset, errors="replace")
            status_code = getattr(response, "status", response.getcode())
            final_url = response.geturl()

        return HttpResponse(
            url=final_url,
            status_code=int(status_code),
            text=text,
            headers=response_headers,
        )


class SourceAdapter(Protocol):
    """Adapter protocol for one approved source access mode."""

    access_mode: str

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        """Discover article references for an approved source."""

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> RawArticleFetch:
        """Fetch raw article data for a discovered reference."""
