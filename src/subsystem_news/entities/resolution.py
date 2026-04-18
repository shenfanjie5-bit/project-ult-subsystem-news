"""Entity resolution orchestration for normalized article mentions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import InvolvedEntity
from subsystem_news.entities.fallback import ambiguous_entity, unresolved_entity
from subsystem_news.entities.mention import Mention, dedupe_mentions, detect_mentions
from subsystem_news.entities.quick_path import resolve_quick_paths
from subsystem_news.entities.resolver_client import (
    EntityRegistryClient,
    RegistryMention,
    RegistryResolution,
    ResolutionCase,
)
from subsystem_news.errors import EntityResolutionError


class ResolvedMention(BaseModel):
    """A mention paired with the entity contract emitted for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mention: Mention
    entity: InvolvedEntity
    resolution_source: Literal["quick_path", "registry", "fallback"]
    registry_resolution: RegistryResolution | None = None
    trace_error: str | None = Field(default=None)


class EntityResolutionResult(BaseModel):
    """Full traceable result for resolving a list of detected mentions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mentions: list[Mention]
    resolved_mentions: list[ResolvedMention]
    entities: list[InvolvedEntity]


_LOCATOR_ORDER = {"title": 0, "body": 1}


def resolve_detected_mentions(
    mentions: Sequence[Mention],
    client: EntityRegistryClient,
) -> EntityResolutionResult:
    """Resolve detected mentions through quick alias lookup, batch registry, and fallback."""

    ordered_mentions = dedupe_mentions(mentions)
    quick_resolved, remaining_mentions = resolve_quick_paths(ordered_mentions, client)
    registry_resolved = _resolve_remaining_mentions(remaining_mentions, client)
    resolved_mentions = sorted(
        [*quick_resolved, *registry_resolved],
        key=lambda resolved: _mention_order_key(resolved.mention),
    )
    return EntityResolutionResult(
        mentions=ordered_mentions,
        resolved_mentions=resolved_mentions,
        entities=_dedupe_entities(resolved_mentions),
    )


def resolve_article_entities(
    article: NewsArticleArtifact,
    client: EntityRegistryClient,
) -> list[InvolvedEntity]:
    """Detect and resolve article entities, returning stable de-duplicated contracts."""

    return resolve_detected_mentions(detect_mentions(article), client).entities


def _resolve_remaining_mentions(
    mentions: Sequence[Mention],
    client: EntityRegistryClient,
) -> list[ResolvedMention]:
    if not mentions:
        return []

    registry_mentions = [RegistryMention.from_mention(mention) for mention in mentions]
    try:
        raw_resolutions = [
            item
            if isinstance(item, RegistryResolution)
            else RegistryResolution.model_validate(item)
            for item in client.resolve_mentions(registry_mentions)
        ]
    except EntityResolutionError:
        raise
    except Exception as exc:
        raise EntityResolutionError("entity-registry resolve_mentions failed") from exc

    resolutions_by_id = {resolution.mention_id: resolution for resolution in raw_resolutions}
    resolved: list[ResolvedMention] = []
    for mention, registry_mention in zip(mentions, registry_mentions, strict=True):
        resolution = resolutions_by_id.get(registry_mention.mention_id)
        if resolution is None:
            resolution = RegistryResolution(
                mention_id=registry_mention.mention_id,
                status="unresolved",
                reason="entity-registry returned no resolution for mention",
            )
        resolved.append(_resolved_mention_from_registry(mention, resolution, client))
    return resolved


def _resolved_mention_from_registry(
    mention: Mention,
    resolution: RegistryResolution,
    client: EntityRegistryClient,
) -> ResolvedMention:
    if resolution.status == "resolved":
        entity = InvolvedEntity(
            mention_text=mention.text,
            canonical_id=resolution.canonical_id,
            resolution_status="resolved",
            type_hint=mention.type_hint,
        )
        return ResolvedMention(
            mention=mention,
            entity=entity,
            resolution_source="registry",
            registry_resolution=resolution,
        )

    if resolution.status == "ambiguous":
        entity = ambiguous_entity(mention)
    else:
        entity = unresolved_entity(mention)

    trace_error = _record_resolution_case(mention, resolution, client)
    return ResolvedMention(
        mention=mention,
        entity=entity,
        resolution_source="fallback",
        registry_resolution=resolution,
        trace_error=trace_error,
    )


def _record_resolution_case(
    mention: Mention,
    resolution: RegistryResolution,
    client: EntityRegistryClient,
) -> str | None:
    registry_mention = RegistryMention.from_mention(mention)
    case = ResolutionCase(
        article_id=mention.article_id,
        mention_id=registry_mention.mention_id,
        mention_text=mention.text,
        type_hint=mention.type_hint,
        context=mention.context,
        source_reference=mention.source_reference,
        resolution_status=resolution.status,
        candidates=resolution.candidates,
        reason=resolution.reason,
    )
    try:
        client.record_resolution_case(case)
    except Exception as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return None


def _mention_order_key(mention: Mention) -> tuple[int, int, int, str]:
    return (
        _LOCATOR_ORDER[mention.locator],
        mention.start_char,
        mention.end_char,
        mention.text,
    )


def _dedupe_entities(resolved_mentions: Sequence[ResolvedMention]) -> list[InvolvedEntity]:
    entities: list[InvolvedEntity] = []
    seen: set[tuple[str, str, str]] = set()
    for resolved in resolved_mentions:
        entity = resolved.entity
        if entity.resolution_status == "resolved" and entity.canonical_id is not None:
            key = (entity.resolution_status, entity.canonical_id, "")
        else:
            key = (
                entity.resolution_status,
                entity.mention_text.casefold(),
                entity.type_hint,
            )
        if key in seen:
            continue
        seen.add(key)
        entities.append(entity)
    return entities
