"""Deterministic alias lookup path for registry-backed entity resolution."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from subsystem_news.contracts.candidates import InvolvedEntity
from subsystem_news.entities.mention import Mention
from subsystem_news.entities.resolver_client import EntityRegistryClient
from subsystem_news.errors import EntityResolutionError

if TYPE_CHECKING:
    from subsystem_news.entities.resolution import ResolvedMention


_QUICK_PATH_TYPE_HINTS = {"stock_code", "company", "standard_abbreviation"}


def is_quick_path_mention(mention: Mention) -> bool:
    """Return whether a mention should try deterministic alias lookup first."""

    return mention.type_hint in _QUICK_PATH_TYPE_HINTS


def resolve_quick_paths(
    mentions: Sequence[Mention],
    client: EntityRegistryClient,
) -> tuple[list["ResolvedMention"], list[Mention]]:
    """Resolve quick-path mentions via lookup_alias and return misses for batching."""

    from subsystem_news.entities.resolution import ResolvedMention

    resolved: list[ResolvedMention] = []
    remaining: list[Mention] = []

    for mention in mentions:
        if not is_quick_path_mention(mention):
            remaining.append(mention)
            continue

        try:
            lookup = client.lookup_alias(mention.text, type_hint=mention.type_hint)
        except EntityResolutionError:
            raise
        except Exception as exc:
            raise EntityResolutionError("entity-registry lookup_alias failed") from exc

        if lookup is None:
            remaining.append(mention)
            continue

        try:
            entity = InvolvedEntity(
                mention_text=mention.text,
                canonical_id=lookup.canonical_id,
                resolution_status="resolved",
                type_hint=mention.type_hint,
            )
        except ValueError as exc:
            raise EntityResolutionError("entity-registry lookup_alias returned invalid entity") from exc

        resolved.append(
            ResolvedMention(
                mention=mention,
                entity=entity,
                resolution_source="quick_path",
                registry_resolution=None,
            )
        )

    return resolved, remaining
