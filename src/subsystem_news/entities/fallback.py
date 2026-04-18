"""Fallback InvolvedEntity constructors for unresolved registry outcomes."""

from __future__ import annotations

from subsystem_news.contracts.candidates import InvolvedEntity
from subsystem_news.entities.mention import Mention


def unresolved_entity(mention: Mention) -> InvolvedEntity:
    """Return an explicit unresolved entity without inventing a canonical id."""

    return InvolvedEntity(
        mention_text=mention.text,
        canonical_id=None,
        resolution_status="unresolved",
        type_hint=mention.type_hint,
    )


def ambiguous_entity(mention: Mention) -> InvolvedEntity:
    """Return an explicit ambiguous entity without selecting a canonical id."""

    return InvolvedEntity(
        mention_text=mention.text,
        canonical_id=None,
        resolution_status="ambiguous",
        type_hint=mention.type_hint,
    )
