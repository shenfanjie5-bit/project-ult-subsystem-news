"""Client protocol and DTOs for entity-registry coordination."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.entities.mention import Mention
from subsystem_news.errors import EntityResolutionError


ResolutionStatus = Literal["resolved", "unresolved", "ambiguous"]


class RegistryMention(BaseModel):
    """Mention payload sent to entity-registry batch resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mention_id: str = Field(min_length=1)
    article_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    locator: Literal["title", "body"]
    type_hint: str = Field(min_length=1)
    context: str
    source_reference: SourceReference

    @model_validator(mode="after")
    def validate_span_order(self) -> "RegistryMention":
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self

    @classmethod
    def from_mention(cls, mention: Mention) -> "RegistryMention":
        return cls(
            mention_id=mention_id_for(mention),
            article_id=mention.article_id,
            text=mention.text,
            start_char=mention.start_char,
            end_char=mention.end_char,
            locator=mention.locator,
            type_hint=mention.type_hint,
            context=mention.context,
            source_reference=mention.source_reference,
        )


class RegistryLookup(BaseModel):
    """Deterministic lookup result from entity-registry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_id: str = Field(min_length=1)
    canonical_name: str | None = None
    entity_type: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_canonical_id(self) -> "RegistryLookup":
        if not self.canonical_id.strip():
            raise ValueError("canonical_id must be non-empty")
        return self


class RegistryCandidate(BaseModel):
    """Candidate entity returned for ambiguous registry resolutions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_id: str = Field(min_length=1)
    canonical_name: str
    entity_type: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RegistryResolution(BaseModel):
    """Batch resolution result for a single mention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mention_id: str = Field(min_length=1)
    status: ResolutionStatus
    canonical_id: str | None = None
    canonical_name: str | None = None
    entity_type: str | None = None
    candidates: list[RegistryCandidate] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_status_canonical_id(self) -> "RegistryResolution":
        if self.status == "resolved":
            if self.canonical_id is None or not self.canonical_id.strip():
                raise ValueError("resolved registry result requires canonical_id")
            return self

        if self.canonical_id is not None:
            raise ValueError(f"{self.status} registry result requires canonical_id to be null")
        return self


class ResolutionCase(BaseModel):
    """Trace record for ambiguous or unresolved mention resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str = Field(min_length=1)
    mention_id: str = Field(min_length=1)
    mention_text: str = Field(min_length=1)
    type_hint: str = Field(min_length=1)
    context: str
    source_reference: SourceReference
    resolution_status: ResolutionStatus
    candidates: list[RegistryCandidate] = Field(default_factory=list)
    reason: str | None = None


class EntityRegistryClient(Protocol):
    """Narrow entity-registry interface consumed by subsystem-news."""

    def lookup_alias(
        self,
        name: str,
        *,
        type_hint: str | None = None,
    ) -> RegistryLookup | None:
        """Resolve deterministic aliases such as tickers and official names."""

    def resolve_mentions(self, mentions: Sequence[RegistryMention]) -> list[RegistryResolution]:
        """Batch resolve non-quick-path mentions."""

    def record_resolution_case(self, case: ResolutionCase) -> None:
        """Persist trace details for ambiguous or unresolved mentions."""


def mention_id_for(mention: Mention) -> str:
    """Build a stable registry mention id from article-local span coordinates."""

    return (
        f"{mention.article_id}:{mention.locator}:"
        f"{mention.start_char}:{mention.end_char}:{mention.text}"
    )


AliasKey = str | tuple[str, str | None]


class StubEntityRegistryClient:
    """In-memory registry client for tests and local fixture replay."""

    def __init__(
        self,
        *,
        alias_results: Mapping[AliasKey, RegistryLookup | Mapping[str, object] | None] | None = None,
        resolutions: Mapping[str, RegistryResolution | Mapping[str, object]] | None = None,
        lookup_exception: Exception | None = None,
        resolve_exception: Exception | None = None,
        record_exception: Exception | None = None,
    ) -> None:
        self._alias_results = {
            key: _lookup_or_none(value) for key, value in (alias_results or {}).items()
        }
        self._resolutions = {
            key: _resolution_from_value(value) for key, value in (resolutions or {}).items()
        }
        self._lookup_exception = lookup_exception
        self._resolve_exception = resolve_exception
        self._record_exception = record_exception
        self.lookup_calls: list[tuple[str, str | None]] = []
        self.resolve_calls: list[list[RegistryMention]] = []
        self.recorded_cases: list[ResolutionCase] = []

    def lookup_alias(
        self,
        name: str,
        *,
        type_hint: str | None = None,
    ) -> RegistryLookup | None:
        self.lookup_calls.append((name, type_hint))
        if self._lookup_exception is not None:
            raise self._lookup_exception

        for key in ((name, type_hint), (name, None), name):
            if key in self._alias_results:
                return self._alias_results[key]
        return None

    def resolve_mentions(self, mentions: Sequence[RegistryMention]) -> list[RegistryResolution]:
        self.resolve_calls.append(list(mentions))
        if self._resolve_exception is not None:
            raise self._resolve_exception

        resolutions: list[RegistryResolution] = []
        for mention in mentions:
            resolution = self._resolutions.get(mention.mention_id) or self._resolutions.get(
                mention.text
            )
            if resolution is None:
                resolution = RegistryResolution(
                    mention_id=mention.mention_id,
                    status="unresolved",
                    reason="stub registry has no configured resolution",
                )
            elif resolution.mention_id != mention.mention_id:
                resolution = resolution.model_copy(update={"mention_id": mention.mention_id})
            resolutions.append(resolution)
        return resolutions

    def record_resolution_case(self, case: ResolutionCase) -> None:
        if self._record_exception is not None:
            raise self._record_exception
        self.recorded_cases.append(case)


class HttpEntityRegistryClient:
    """HTTP entity-registry client using only Python standard-library transport."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def lookup_alias(
        self,
        name: str,
        *,
        type_hint: str | None = None,
    ) -> RegistryLookup | None:
        query = {"name": name}
        if type_hint is not None:
            query["type_hint"] = type_hint
        try:
            payload = self._request_json("GET", "lookup_alias", query=query)
        except EntityResolutionError as exc:
            if exc.__cause__ is not None and isinstance(exc.__cause__, HTTPError):
                if exc.__cause__.code == 404:
                    return None
            raise
        if payload is None:
            return None
        return RegistryLookup.model_validate(payload)

    def resolve_mentions(self, mentions: Sequence[RegistryMention]) -> list[RegistryResolution]:
        payload = {
            "mentions": [mention.model_dump(mode="json") for mention in mentions],
        }
        data = self._request_json("POST", "resolve_mentions", payload=payload)
        raw_resolutions = data.get("resolutions", data) if isinstance(data, dict) else data
        if not isinstance(raw_resolutions, list):
            raise EntityResolutionError("entity-registry resolve_mentions returned invalid payload")
        return [RegistryResolution.model_validate(item) for item in raw_resolutions]

    def record_resolution_case(self, case: ResolutionCase) -> None:
        self._request_json(
            "POST",
            "resolution_cases",
            payload=case.model_dump(mode="json"),
        )

    def _request_json(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        url = urljoin(self.base_url, path)
        if query:
            url = f"{url}?{urlencode(query)}"

        body: bytes | None = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                raw_body = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise EntityResolutionError("entity-registry HTTP request failed") from exc

        if not raw_body:
            return None
        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise EntityResolutionError("entity-registry returned malformed JSON") from exc


def _lookup_or_none(value: RegistryLookup | Mapping[str, object] | None) -> RegistryLookup | None:
    if value is None:
        return None
    if isinstance(value, RegistryLookup):
        return value
    return RegistryLookup.model_validate(value)


def _resolution_from_value(
    value: RegistryResolution | Mapping[str, object],
) -> RegistryResolution:
    if isinstance(value, RegistryResolution):
        return value
    return RegistryResolution.model_validate(value)
