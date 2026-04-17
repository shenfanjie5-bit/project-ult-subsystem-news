"""Subsystem-specific exception types."""


class SubsystemNewsError(Exception):
    """Base exception for subsystem-news failures."""

    code: str = "subsystem_news_error"


class SourceNotApprovedError(SubsystemNewsError):
    """Raised when a news source is not in the approved allowlist."""

    code: str = "source_not_approved"


class EvidenceMissingError(SubsystemNewsError):
    """Raised when a candidate lacks required evidence spans."""

    code: str = "evidence_missing"


class EntityResolutionError(SubsystemNewsError):
    """Raised when entity resolution cannot produce a valid result."""

    code: str = "entity_resolution_error"


class ContractViolationError(SubsystemNewsError):
    """Raised when local candidate validation violates an output contract."""

    code: str = "contract_violation"
