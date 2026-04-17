"""Source-layer DTOs, protocols, and HTTP transport."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Mapping, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.contracts import NewsSourceConfig, SourceReference


class NewsArticleRef(BaseModel):
    """Traceable reference discovered from an approved source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    source_reference: SourceReference
    url: str | None = Field(default=None, min_length=1)
    provider_key: str | None = Field(default=None, min_length=1)
    title_hint: str | None = None
    published_at_hint: datetime | None = None
    cursor: str | None = None

    @model_validator(mode="after")
    def validate_traceability(self) -> "NewsArticleRef":
        if self.source_reference.source_id != self.source_id:
            raise ValueError("source_reference.source_id must match source_id")
        if self.url is None and self.provider_key is None:
            raise ValueError("article reference requires url or provider_key")
        return self


class RawArticleFetch(BaseModel):
    """Raw article payload returned by a source adapter."""

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
    content_hash: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_matches_ref(self) -> "RawArticleFetch":
        if self.source.source_id != self.ref.source_id:
            raise ValueError("source.source_id must match ref.source_id")
        return self


class FetchTrace(BaseModel):
    """Small trace record for a raw fetch without article body leakage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_reference: SourceReference
    url: str | None = Field(default=None, min_length=1)
    provider_key: str | None = Field(default=None, min_length=1)
    content_hash: str = Field(min_length=1)
    fetched_at: datetime
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_trace_reference(self) -> "FetchTrace":
        if self.source_reference.source_id != self.source_id:
            raise ValueError("source_reference.source_id must match source_id")
        if self.url is None and self.provider_key is None:
            raise ValueError("fetch trace requires url or provider_key")
        return self


class HttpResponse(BaseModel):
    """HTTP response body captured by source adapters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    status_code: int
    text: str
    headers: Mapping[str, str] = Field(default_factory=dict)


class HttpTransport(Protocol):
    """Minimal HTTP transport used by source adapters."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Fetch a URL and return a decoded text response."""


class UrllibHttpTransport:
    """Standard-library HTTP transport."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        request = Request(url, headers=dict(headers or {}), method="GET")

        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                response_headers = {str(key): str(value) for key, value in response.headers.items()}
                charset = response.headers.get_content_charset() or "utf-8"
                return HttpResponse(
                    url=response.geturl(),
                    status_code=response.status,
                    text=body.decode(charset, errors="replace"),
                    headers=response_headers,
                )
        except HTTPError as exc:
            body = exc.read()
            response_headers = {str(key): str(value) for key, value in exc.headers.items()}
            charset = exc.headers.get_content_charset() or "utf-8"
            return HttpResponse(
                url=exc.geturl(),
                status_code=exc.code,
                text=body.decode(charset, errors="replace"),
                headers=response_headers,
            )


class SourceAdapter(Protocol):
    """Adapter for one approved source access mode."""

    access_mode: str

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        """Discover article references from a source."""

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> RawArticleFetch:
        """Fetch the raw article payload for a discovered reference."""


def utc_now() -> datetime:
    """Return an aware UTC timestamp for fetch records."""

    return datetime.now(timezone.utc)


def content_hash_for(raw_payload: Mapping[str, str | None]) -> str:
    """Build a stable hash for adapter raw payload fields."""

    encoded = json.dumps(
        dict(sorted(raw_payload.items())),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def trace_id_for(ref: NewsArticleRef, content_hash: str, fetched_at: datetime) -> str:
    """Build a deterministic trace id from fetch metadata."""

    payload = {
        "source_reference": ref.source_reference.model_dump(mode="json"),
        "content_hash": content_hash,
        "fetched_at": fetched_at.isoformat(),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
