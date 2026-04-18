"""Mention extraction and entity-registry resolution coordination."""

from subsystem_news.entities.fallback import ambiguous_entity, unresolved_entity
from subsystem_news.entities.mention import Mention, dedupe_mentions, detect_mentions
from subsystem_news.entities.quick_path import is_quick_path_mention, resolve_quick_paths
from subsystem_news.entities.resolution import (
    EntityResolutionResult,
    ResolvedMention,
    resolve_article_entities,
    resolve_detected_mentions,
)
from subsystem_news.entities.resolver_client import (
    EntityRegistryClient,
    HttpEntityRegistryClient,
    RegistryCandidate,
    RegistryLookup,
    RegistryMention,
    RegistryResolution,
    ResolutionCase,
    StubEntityRegistryClient,
)

__all__ = [
    "EntityRegistryClient",
    "EntityResolutionResult",
    "HttpEntityRegistryClient",
    "Mention",
    "RegistryCandidate",
    "RegistryLookup",
    "RegistryMention",
    "RegistryResolution",
    "ResolvedMention",
    "ResolutionCase",
    "StubEntityRegistryClient",
    "ambiguous_entity",
    "dedupe_mentions",
    "detect_mentions",
    "is_quick_path_mention",
    "resolve_article_entities",
    "resolve_detected_mentions",
    "resolve_quick_paths",
    "unresolved_entity",
]
