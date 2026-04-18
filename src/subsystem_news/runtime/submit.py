"""Candidate validation and subsystem-sdk submit boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from subsystem_news.contracts.candidates import NewsFactCandidate, NewsSignalCandidate
from subsystem_news.errors import ContractViolationError
from subsystem_news.runtime.models import CandidatePayload


class SubmitReceipt(BaseModel):
    """Normalized receipt returned by the subsystem-sdk submit adapter."""

    model_config = ConfigDict(extra="forbid")

    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(default=0, ge=0)
    submitted_candidate_ids: list[str] = Field(default_factory=list)
    rejected_candidate_ids: list[str] = Field(default_factory=list)
    receipt_id: str | None = None


class SubsystemSdkClient(Protocol):
    """Narrow submit protocol used by runtime tests and adapters."""

    def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
        """Submit a locally validated batch of Ex candidates."""


class DefaultSubsystemSdkClient:
    """Lazy adapter around ``subsystem_sdk.submit``."""

    def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
        from subsystem_sdk import submit as sdk_submit

        payload = [candidate.model_dump(mode="json") for candidate in batch]
        response = sdk_submit(payload)
        if isinstance(response, SubmitReceipt):
            receipt = response
            _require_receipt_partitions_batch(receipt, batch)
            return receipt
        if isinstance(response, Mapping):
            try:
                receipt = SubmitReceipt.model_validate(response)
            except (ValidationError, ValueError, TypeError) as exc:
                raise ContractViolationError(
                    "subsystem-sdk submit returned invalid receipt"
                ) from exc
            _require_receipt_partitions_batch(receipt, batch)
            return receipt
        if response is None:
            raise ContractViolationError(
                "subsystem-sdk submit returned no receipt; accepted candidate IDs "
                "are ambiguous"
            )
        raise ContractViolationError("subsystem-sdk submit returned unsupported receipt")


def validate_candidate_batch(batch: Sequence[CandidatePayload]) -> list[CandidatePayload]:
    """Revalidate candidates and reject payloads that cannot be submitted."""

    validated: list[CandidatePayload] = []
    for candidate in batch:
        validated.append(_validate_candidate(candidate))
    return validated


def submit_candidates(
    batch: Sequence[CandidatePayload],
    client: SubsystemSdkClient,
    *,
    max_retries: int = 2,
) -> SubmitReceipt:
    """Validate and submit a candidate batch, retrying transient client failures."""

    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")

    validated = validate_candidate_batch(batch)
    if not validated:
        return SubmitReceipt(accepted_count=0, rejected_count=0, receipt_id="empty-batch")

    last_error: Exception | None = None
    for _attempt in range(max_retries + 1):
        try:
            receipt = client.submit(validated)
            if isinstance(receipt, SubmitReceipt):
                return receipt
            if isinstance(receipt, Mapping):
                try:
                    return SubmitReceipt.model_validate(receipt)
                except (ValidationError, ValueError, TypeError) as exc:
                    raise ContractViolationError(
                        "submit client returned invalid receipt"
                    ) from exc
            raise ContractViolationError("submit client returned unsupported receipt")
        except ContractViolationError:
            raise
        except Exception as exc:  # noqa: BLE001 - submit clients decide which failures are transient.
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError("submit failed without an exception")


def _validate_candidate(candidate: CandidatePayload) -> CandidatePayload:
    if isinstance(candidate, NewsFactCandidate):
        _require_candidate_common_fields(candidate, expected_contract="Ex-1")
        return _revalidate_fact(candidate)
    if isinstance(candidate, NewsSignalCandidate):
        _require_candidate_common_fields(candidate, expected_contract="Ex-2")
        _require_signal_fields(candidate)
        return _revalidate_signal(candidate)
    raise ContractViolationError("candidate must be NewsFactCandidate or NewsSignalCandidate")


def _require_candidate_common_fields(
    candidate: CandidatePayload,
    *,
    expected_contract: str,
) -> None:
    if getattr(candidate, "source_reference", None) is None:
        raise ContractViolationError("candidate requires source_reference")
    evidence_spans = getattr(candidate, "evidence_spans", None)
    if not evidence_spans:
        raise ContractViolationError("candidate requires non-empty evidence_spans")
    if getattr(candidate, "export_contract", None) != expected_contract:
        raise ContractViolationError(f"candidate export_contract must be {expected_contract}")


def _require_signal_fields(candidate: NewsSignalCandidate) -> None:
    if getattr(candidate, "direction", None) is None:
        raise ContractViolationError("Ex-2 candidate requires direction")
    magnitude = getattr(candidate, "magnitude", None)
    if magnitude is None or (isinstance(magnitude, str) and not magnitude.strip()):
        raise ContractViolationError("Ex-2 candidate requires magnitude")
    if not getattr(candidate, "affected_entities", None):
        raise ContractViolationError("Ex-2 candidate requires affected_entities")


def _revalidate_fact(candidate: NewsFactCandidate) -> NewsFactCandidate:
    try:
        return NewsFactCandidate.model_validate(candidate.model_dump(mode="json"))
    except (ValidationError, ValueError, TypeError) as exc:
        raise ContractViolationError("candidate violates Ex-1 contract") from exc


def _revalidate_signal(candidate: NewsSignalCandidate) -> NewsSignalCandidate:
    try:
        return NewsSignalCandidate.model_validate(candidate.model_dump(mode="json"))
    except (ValidationError, ValueError, TypeError) as exc:
        raise ContractViolationError("candidate violates Ex-2 contract") from exc


def _require_receipt_partitions_batch(
    receipt: SubmitReceipt,
    batch: Sequence[CandidatePayload],
) -> None:
    batch_ids = [candidate.candidate_id for candidate in batch]
    known_ids = set(batch_ids)
    if len(known_ids) != len(batch_ids):
        raise ContractViolationError("submit batch contains duplicate candidate_id values")

    if receipt.accepted_count + receipt.rejected_count != len(batch):
        raise ContractViolationError("submit receipt counts must equal submitted batch size")

    accepted_ids = set(receipt.submitted_candidate_ids)
    rejected_ids = set(receipt.rejected_candidate_ids)
    if len(accepted_ids) != len(receipt.submitted_candidate_ids):
        raise ContractViolationError(
            "submit receipt submitted_candidate_ids must not contain duplicates"
        )
    if len(rejected_ids) != len(receipt.rejected_candidate_ids):
        raise ContractViolationError(
            "submit receipt rejected_candidate_ids must not contain duplicates"
        )
    unknown_ids = (accepted_ids | rejected_ids) - known_ids
    if unknown_ids:
        raise ContractViolationError(
            "submit receipt references unknown candidate_id values: "
            f"{', '.join(sorted(unknown_ids))}"
        )

    overlapping_ids = accepted_ids & rejected_ids
    if overlapping_ids:
        raise ContractViolationError(
            "submit receipt lists candidate_id values as both accepted and rejected: "
            f"{', '.join(sorted(overlapping_ids))}"
        )

    if len(accepted_ids) != receipt.accepted_count:
        raise ContractViolationError(
            "submit receipt submitted_candidate_ids must match accepted_count"
        )
    if len(rejected_ids) != receipt.rejected_count:
        raise ContractViolationError(
            "submit receipt rejected_candidate_ids must match rejected_count"
        )
    if accepted_ids | rejected_ids != known_ids:
        raise ContractViolationError(
            "submit receipt candidate IDs must partition the submitted batch"
        )
