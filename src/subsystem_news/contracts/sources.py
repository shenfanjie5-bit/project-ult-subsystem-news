"""Approved news source configuration contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError

from subsystem_news.errors import ContractViolationError, SourceNotApprovedError


class NewsSourceConfig(BaseModel):
    """Frozen config entry for an approved source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    display_name: str
    access_mode: Literal["rss", "api", "site_html"]
    base_url: HttpUrl
    approved: bool
    reliability_tier: Literal["A", "B", "C"]
    license_tag: str
    language: str
    credential_ref: str | None


def load_allowlist(path: Path) -> list[NewsSourceConfig]:
    """Load approved source configs and reject non-approved entries."""

    raw_sources = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_sources, list):
        raise ContractViolationError("source allowlist must be a JSON array")

    try:
        sources = [NewsSourceConfig.model_validate(item) for item in raw_sources]
    except ValidationError as exc:
        raise ContractViolationError("source allowlist violates NewsSourceConfig") from exc

    blocked = [source.source_id for source in sources if not source.approved]
    if blocked:
        blocked_ids = ", ".join(blocked)
        raise SourceNotApprovedError(f"source allowlist contains unapproved entries: {blocked_ids}")

    return sources
