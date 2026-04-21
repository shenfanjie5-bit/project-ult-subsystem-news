"""Candidate validation and subsystem-sdk submit boundary.

Stage 2.9 cross-repo reconciliation (sibling of subsystem-announcement
follow-up #3): adds ``_normalize_for_sdk(local_payload, ex_type)``, the
production canonical mapper that converts a news-local candidate's
``model_dump`` shape to the canonical ``contracts.schemas.Ex1/2/3``
wire shape. Without this normalizer the real SDK link
(``BaseSubsystemContext.submit -> SubmitClient.submit ->
validate_then_dispatch -> validate_payload ->
contracts.Ex*.model_validate``) would reject news payloads via
``extra='forbid'`` because of cross-repo schema mismatches:

  - news ``candidate_id`` vs canonical ``fact_id``/``signal_id``/``delta_id``
  - news ``involved_entities``/``subject_entity``/``object_entity``
    (rich ``InvolvedEntity`` objects) vs canonical
    ``entity_id``/``source_node``/``target_node`` (string IDs)
  - news ``Direction`` (``positive``/``negative``/``neutral``/``mixed``)
    vs canonical ``contracts.Direction``
    (``bullish``/``bearish``/``neutral``)
  - news ``magnitude`` (``str | float``) vs canonical ``Magnitude``
    (strict float, ge=0.0)
  - news ``evidence_spans`` (full ``EvidenceSpan`` objects) vs canonical
    ``evidence: list[EvidenceRef]`` (deterministic ref strings)
  - news has no ``produced_at`` field on the candidate; canonical
    requires SDK-routing ``produced_at`` (added by mapper at submit time)
  - many news-local fields (``article_id``, ``cluster_id``, ``summary``,
    ``rationale``, ``impact_scope``, ``source_reliability_tier``,
    ``involved_entities`` original, etc.) have no canonical wire slot
    and go into ``producer_context`` (contracts v0.1.3 extension slot).

The mapper output is what ``contracts.Ex*.model_validate`` accepts
directly after ``_strip_sdk_envelope``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from subsystem_news.contracts.candidates import (
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.errors import ContractViolationError
from subsystem_news.runtime.models import CandidatePayload
from subsystem_news.version import __version__ as _NEWS_VERSION


MODULE_ID: Final[str] = "subsystem-news"

# news ``Direction`` (``positive``/``negative``/``neutral``/``mixed``) →
# contracts ``Direction`` (``bullish``/``bearish``/``neutral``). News's
# ``mixed`` has no canonical equivalent; mapped to ``neutral`` and the
# original value preserved in ``producer_context["original_direction"]``
# so Layer B replay/audit can reconstruct the news-local intent.
_NEWS_DIRECTION_TO_CONTRACTS_DIRECTION: dict[str, str] = {
    "positive": "bullish",
    "negative": "bearish",
    "neutral": "neutral",
    "mixed": "neutral",
}


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
    """Lazy adapter around ``subsystem_sdk.submit``.

    Stage 2.9 canonical-mapper rewrite: the SDK submit API takes ONE
    canonical wire payload per call (``submit_sdk(payload: Mapping)``);
    news's local protocol takes a batch. This adapter iterates per-
    candidate, runs each through the canonical mapper
    (``_validated_payload``), and aggregates the per-call SDK
    ``SubmitReceipt`` (an SDK-shape receipt with single-payload fields)
    into news's batch-shape ``SubmitReceipt`` (with accepted_count /
    rejected_count / partitioned candidate_id lists).
    """

    def submit(self, batch: Sequence[CandidatePayload]) -> SubmitReceipt:
        # ``subsystem_sdk.submit`` (top-level attribute) is the SUBMODULE,
        # not the function. Import the function explicitly to avoid the
        # ``'module' object is not callable`` trap.
        from subsystem_sdk.submit import submit as sdk_submit

        # Stage 2.9 follow-up #1 (codex review #1 P1 #1): the SDK's
        # top-level ``submit()`` delegates to ``get_runtime().submit()``,
        # which raises ``RuntimeNotConfiguredError`` if no
        # ``BaseSubsystemContext`` was bound via
        # ``configure_runtime(...)``. The original orchestrator default
        # constructed ``DefaultSubsystemSdkClient()`` without any
        # surrounding ``configure_runtime`` scope — so the first real
        # non-dry-run submission would crash with a cryptic SDK error.
        # Catch the SDK-internal RuntimeNotConfiguredError and re-raise
        # with news-specific guidance pointing at the orchestrator
        # contract: callers MUST either (a) pass an ``sdk_client=`` to
        # ``run_once`` for non-dry-run mode, or (b) configure the SDK
        # runtime explicitly via ``configure_runtime(context)`` around
        # the pipeline execution.
        from subsystem_sdk.base.runtime import RuntimeNotConfiguredError

        # Stage 2.9 follow-up #2 (codex review #2 P1): partition the
        # batch at the canonical wire boundary. The news upstream
        # extract path intentionally produces unresolved Ex-1 / Ex-2
        # candidates for local traceability (see
        # ``test_all_unresolved_boundary_emits_traceable_ex1_fact``);
        # those reach this adapter as part of the validated batch. The
        # canonical mapper REJECTS unresolved entities at canonical
        # wire positions (CLAUDE.md #6 — never fabricate canonical
        # IDs), so we partition here: submittable candidates go through
        # the SDK; unresolved ones are recorded as rejected in the
        # receipt without crossing the wire boundary. This preserves
        # the upstream traceability contract AND the canonical-ID
        # invariant simultaneously.
        submittable, skipped_unresolved = _partition_for_submit(batch)

        accepted_ids: list[str] = []
        rejected_ids: list[str] = [
            candidate.candidate_id for candidate, _ in skipped_unresolved
        ]
        last_receipt_id: str | None = None

        for candidate in submittable:
            wire_payload = _validated_payload(candidate)
            try:
                sdk_receipt = sdk_submit(wire_payload)
            except RuntimeNotConfiguredError as exc:
                raise ContractViolationError(
                    "DefaultSubsystemSdkClient.submit requires the "
                    "subsystem_sdk runtime to be bound via "
                    "configure_runtime(BaseSubsystemContext(...)) "
                    "before .submit() is called. For non-dry-run "
                    "pipelines, either pass sdk_client= to run_once "
                    "(with your wired backend), or wrap the pipeline "
                    "call in configure_runtime(...). For tests / smoke, "
                    "see tests/integration/test_sdk_wire_shape_integration.py "
                    "for the canonical wiring pattern."
                ) from exc
            # SDK SubmitReceipt has ``accepted: bool`` + ``receipt_id``
            # + ``backend_kind`` + per-call error/warning lists. Reject
            # ``None`` and shapes that don't expose ``accepted`` so we
            # don't silently treat ambiguous SDK responses as accepted
            # candidates (preserves the safety guarantee tests around
            # ``DefaultSubsystemSdkClient`` originally enforced).
            if sdk_receipt is None:
                raise ContractViolationError(
                    "subsystem-sdk submit returned no receipt; accepted "
                    "candidate IDs are ambiguous"
                )
            if not hasattr(sdk_receipt, "accepted"):
                raise ContractViolationError(
                    "subsystem-sdk submit returned unsupported receipt; "
                    f"expected SubmitReceipt-like object with .accepted, "
                    f"got {type(sdk_receipt).__name__}"
                )
            if sdk_receipt.accepted:
                accepted_ids.append(candidate.candidate_id)
            else:
                rejected_ids.append(candidate.candidate_id)
            last_receipt_id = (
                getattr(sdk_receipt, "receipt_id", None) or last_receipt_id
            )

        receipt = SubmitReceipt(
            accepted_count=len(accepted_ids),
            rejected_count=len(rejected_ids),
            submitted_candidate_ids=accepted_ids,
            rejected_candidate_ids=rejected_ids,
            receipt_id=last_receipt_id,
        )
        _require_receipt_partitions_batch(receipt, batch)
        return receipt


def validate_candidate_batch(batch: Sequence[CandidatePayload]) -> list[CandidatePayload]:
    """Revalidate candidates and reject payloads that cannot be submitted."""

    validated: list[CandidatePayload] = []
    for candidate in batch:
        validated.append(_validate_candidate(candidate))
    return validated


def _unresolved_canonical_position_reason(
    candidate: CandidatePayload,
) -> str | None:
    """Return a reason string if the candidate has unresolved entities at
    a canonical wire position (Ex-1 primary, Ex-2 affected_entities, Ex-3
    subject/object); ``None`` if all canonical-position entities are
    resolved.

    Stage 2.9 follow-up #2 (codex review #2 P1): the canonical wire
    boundary REJECTS unresolved entities (CLAUDE.md #6 — never
    fabricate canonical IDs). But the upstream extract path
    intentionally produces unresolved Ex-1/Ex-2 candidates for local
    traceability (see ``test_all_unresolved_boundary_emits_traceable_ex1_fact``
    in tests/extract). The submit boundary therefore needs a per-
    candidate skip path: rather than abort the entire batch on the
    first unresolved candidate, partition the batch into submittable
    (all canonical-position entities resolved) and
    skipped_unresolved (one or more canonical-position entities
    unresolved/ambiguous). The skipped candidates are recorded in the
    receipt as rejected with their reason; the rest of the batch
    proceeds to the SDK.
    """

    if isinstance(candidate, NewsFactCandidate):
        primary = (
            candidate.involved_entities[0]
            if candidate.involved_entities
            else None
        )
        if primary is None:
            return "Ex-1 candidate has no involved_entities"
        if (
            primary.resolution_status != "resolved"
            or not primary.canonical_id
        ):
            return (
                "Ex-1 primary involved_entities[0] is "
                f"{primary.resolution_status} "
                f"(mention_text={primary.mention_text!r}); "
                "canonical wire entity_id requires resolved entity"
            )
        return None

    if isinstance(candidate, NewsSignalCandidate):
        for idx, entity in enumerate(candidate.affected_entities):
            if (
                entity.resolution_status != "resolved"
                or not entity.canonical_id
            ):
                return (
                    f"Ex-2 affected_entities[{idx}] is "
                    f"{entity.resolution_status} "
                    f"(mention_text={entity.mention_text!r}); "
                    "canonical wire affected_entities require resolved entities"
                )
        return None

    if isinstance(candidate, NewsGraphDeltaCandidate):
        # Ex-3 is already filtered by ``_require_graph_fields`` in
        # ``_validate_candidate``, so this is belt-and-suspenders.
        for role, entity in (
            ("subject_entity", candidate.subject_entity),
            ("object_entity", candidate.object_entity),
        ):
            if (
                entity.resolution_status != "resolved"
                or not entity.canonical_id
            ):
                return (
                    f"Ex-3 {role} is {entity.resolution_status} "
                    f"(mention_text={entity.mention_text!r}); "
                    "canonical wire source_node/target_node require "
                    "resolved entities"
                )
        return None

    return None


def _partition_for_submit(
    batch: Sequence[CandidatePayload],
) -> tuple[
    list[CandidatePayload],
    list[tuple[CandidatePayload, str]],
]:
    """Partition a validated batch into (submittable, skipped_unresolved).

    Skipped candidates are paired with a reason string so the receipt
    + downstream tracing can record exactly why each one was rejected.
    Stage 2.9 follow-up #2 (codex review #2 P1): preserves the upstream
    "produce unresolved Ex-1/Ex-2 candidates for traceability" path
    by deferring the wire-boundary rejection to a per-candidate skip
    rather than a whole-batch abort.
    """

    submittable: list[CandidatePayload] = []
    skipped_unresolved: list[tuple[CandidatePayload, str]] = []
    for candidate in batch:
        reason = _unresolved_canonical_position_reason(candidate)
        if reason is None:
            submittable.append(candidate)
        else:
            skipped_unresolved.append((candidate, reason))
    return submittable, skipped_unresolved


def _merge_skipped_into_receipt(
    client_receipt: SubmitReceipt,
    skipped_unresolved: Sequence[tuple[CandidatePayload, str]],
) -> SubmitReceipt:
    """Fold skipped-at-wire-boundary candidates into a client receipt.

    Skipped candidates count as rejected (they did NOT reach Layer B).
    The candidate_id partition of the merged receipt covers the union
    of (client-submitted accepted + client-submitted rejected + skipped).
    """

    if not skipped_unresolved:
        return client_receipt
    skipped_ids = [candidate.candidate_id for candidate, _ in skipped_unresolved]
    return SubmitReceipt(
        accepted_count=client_receipt.accepted_count,
        rejected_count=client_receipt.rejected_count + len(skipped_unresolved),
        submitted_candidate_ids=list(client_receipt.submitted_candidate_ids),
        rejected_candidate_ids=[
            *client_receipt.rejected_candidate_ids,
            *skipped_ids,
        ],
        receipt_id=client_receipt.receipt_id,
    )


def submit_candidates(
    batch: Sequence[CandidatePayload],
    client: SubsystemSdkClient,
    *,
    max_retries: int = 2,
) -> SubmitReceipt:
    """Validate and submit a candidate batch, retrying transient client failures.

    Stage 2.9 follow-up #2 (codex review #2 P1) deliberately does NOT
    partition unresolved candidates here. The news pipeline contract
    (locked in by ``test_pipeline_submits_unresolved_ex1_only_without_ex2_promotion``)
    is that ``SubsystemSdkClient.submit`` receives the FULL batch
    including unresolved Ex-1 candidates — the SDK adapter
    (``DefaultSubsystemSdkClient``) is responsible for the canonical
    wire boundary partition (CLAUDE.md #6: never fabricate canonical
    IDs from unresolved entities). Test SDK clients (recording fakes)
    and other transports may handle unresolved candidates differently;
    the protocol stays neutral here.
    """

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
                _require_receipt_partitions_batch(receipt, validated)
                return receipt
            if isinstance(receipt, Mapping):
                try:
                    parsed_receipt = SubmitReceipt.model_validate(receipt)
                except (ValidationError, ValueError, TypeError) as exc:
                    raise ContractViolationError(
                        "submit client returned invalid receipt"
                    ) from exc
                _require_receipt_partitions_batch(parsed_receipt, validated)
                return parsed_receipt
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
    if isinstance(candidate, NewsGraphDeltaCandidate):
        _require_candidate_common_fields(candidate, expected_contract="Ex-3")
        _require_graph_fields(candidate)
        return _revalidate_graph(candidate)
    raise ContractViolationError(
        "candidate must be NewsFactCandidate, NewsSignalCandidate, or NewsGraphDeltaCandidate"
    )


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


def _require_graph_fields(candidate: NewsGraphDeltaCandidate) -> None:
    if candidate.requires_manual_review is not True:
        raise ContractViolationError(
            "Ex-3 candidate requires requires_manual_review=true"
        )
    for role, entity in (
        ("subject", candidate.subject_entity),
        ("object", candidate.object_entity),
    ):
        if entity.resolution_status != "resolved" or entity.canonical_id is None:
            raise ContractViolationError(
                f"Ex-3 candidate requires resolved {role}_entity with canonical_id"
            )


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


def _revalidate_graph(candidate: NewsGraphDeltaCandidate) -> NewsGraphDeltaCandidate:
    try:
        return NewsGraphDeltaCandidate.model_validate(candidate.model_dump(mode="json"))
    except (ValidationError, ValueError, TypeError) as exc:
        raise ContractViolationError("candidate violates Ex-3 contract") from exc


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


# ── Stage 2.9 canonical wire mapper ──────────────────────────────────


def _serialize_evidence_ref(span: Mapping[str, Any]) -> str:
    """Deterministic wire-ref string for an EvidenceSpan.

    Format: ``"{article_id}#{locator}:{start_char}-{end_char}"``
    Each ref is self-contained (Layer B can correlate back to
    ``producer_context.evidence_spans_detail`` for quote detail without
    a side-channel lookup). Each ref is min_length=1 (well above
    contracts.EvidenceRef requirement; article_id + locator are
    themselves min_length=1).
    """

    article_id = str(span.get("article_id", ""))
    locator = str(span.get("locator", "body"))
    start_char = span.get("start_char", 0)
    end_char = span.get("end_char", 0)
    return f"{article_id}#{locator}:{start_char}-{end_char}"


def _require_canonical_id(
    entity: Mapping[str, Any] | None, *, role: str
) -> str:
    """Extract a canonical entity_id string from an InvolvedEntity dict.

    Stage 2.9 follow-up #1 (codex review #1 P1 #2): the canonical wire
    boundary MUST NOT fabricate canonical IDs for unresolved or
    ambiguous entities. CLAUDE.md #6 (subsystem-news) is explicit:
    实体 canonical ID 来源必须来自 entity-registry，禁止本模块自造 ID.
    The earlier design synthesized ``"UNRESOLVED:{mention_text}"`` and
    emitted those at top-level (``entity_id`` / ``affected_entities`` /
    ``source_node`` / ``target_node``), which violated the contract by
    letting unresolved entities masquerade as canonical at the Layer B
    ingest boundary.

    Now: if ``canonical_id`` is missing or non-string-non-empty, raise
    ``ContractViolationError``. The full ``InvolvedEntity`` (with
    ``canonical_id=None`` + ``resolution_status='unresolved'`` /
    ``ambiguous``) is still preserved in ``producer_context`` for audit
    / replay; the candidate must be filtered earlier in the pipeline
    (e.g. ``_require_graph_fields`` already does this for Ex-3) or
    held back from submission entirely.

    ``role`` describes the wire field for the error message
    (``entity_id`` / ``affected_entities[i]`` / ``source_node`` /
    ``target_node``).
    """

    if entity is None:
        raise ContractViolationError(
            f"canonical wire field {role!r} requires a resolved "
            "InvolvedEntity; got None. Filter unresolved candidates "
            "before they reach _normalize_for_sdk; see CLAUDE.md #6 "
            "(canonical IDs must come from entity-registry, never "
            "fabricated)."
        )
    canonical = entity.get("canonical_id")
    if not isinstance(canonical, str) or not canonical.strip():
        mention = str(entity.get("mention_text", "<unknown>")).strip() or "<unknown>"
        status = entity.get("resolution_status", "<unknown>")
        raise ContractViolationError(
            f"canonical wire field {role!r} requires a resolved "
            f"InvolvedEntity with non-empty canonical_id; got "
            f"resolution_status={status!r}, mention_text={mention!r}, "
            "canonical_id missing. CLAUDE.md #6: canonical IDs come "
            "from entity-registry only; do not fabricate."
        )
    return canonical


def _coerce_magnitude(magnitude: Any) -> float:
    """Coerce news ``magnitude`` (``str | float``) to canonical
    ``Magnitude`` (strict float, ge=0.0).

    Numeric values pass through. String values try float() conversion
    first; if that fails (e.g. ``"high"``/``"low"``/``"medium"`` string
    levels), map to a stable proxy: ``high=0.8`` / ``medium=0.5`` /
    ``low=0.2``. Unknown string values raise ``ContractViolationError``
    rather than silently emitting nonsense to the wire.
    """

    if isinstance(magnitude, (int, float)):
        return float(magnitude)
    if isinstance(magnitude, str):
        text = magnitude.strip().lower()
        try:
            return float(text)
        except ValueError:
            pass
        proxy_map = {"high": 0.8, "medium": 0.5, "low": 0.2}
        if text in proxy_map:
            return proxy_map[text]
        raise ContractViolationError(
            f"Ex-2 magnitude string {magnitude!r} not coercible to "
            f"contracts.Magnitude (numeric or one of {sorted(proxy_map)})"
        )
    raise ContractViolationError(
        f"Ex-2 magnitude must be float or str, got {type(magnitude)!r}"
    )


def _now_iso() -> str:
    """UTC-now as ISO string. Used for ``produced_at`` SDK envelope
    field — news candidate models have no production timestamp field, so
    the mapper stamps the wire payload at submit time. SDK strips this
    before contracts validation.
    """

    return datetime.now(UTC).isoformat()


def _normalize_for_sdk(
    local_payload: dict[str, Any], ex_type: str
) -> dict[str, Any]:
    """Map a news-local candidate wire dict to the canonical
    ``contracts.schemas.Ex1 / Ex2 / Ex3`` wire shape.

    Output is what ``contracts.Ex*.model_validate`` accepts directly
    (after ``_strip_sdk_envelope`` removes ``ex_type`` /
    ``semantic`` / ``produced_at``).

    Critical mapping notes (mirrors announcement follow-up #3):

    - **``ex_type`` stays at top-level** for SDK envelope routing
      (``_identify_ex_type`` requires it on dict payloads). SDK strips
      before contracts validation.
    - **``produced_at`` stays at top-level** for SDK envelope routing
      (current UTC ISO string; news has no candidate-side production
      timestamp). SDK strips before contracts validation.
    - **Ex-1 ``source_reference`` STAYS at top-level** (contracts.Ex1
      REQUIRED). Ex-2/Ex-3 contracts have NO ``source_reference`` slot,
      so it goes into ``producer_context`` for those.
    - **InvolvedEntity → canonical entity_id strings** —
      ``involved_entities[0]`` becomes Ex-1 ``entity_id``;
      ``affected_entities`` (Ex-2) become a list of canonical_id
      strings; ``subject_entity``/``object_entity`` (Ex-3) become
      ``source_node``/``target_node``. Full ``InvolvedEntity`` objects
      preserved in ``producer_context``.
    - **news ``Direction`` → contracts ``Direction`` enum mapping**
      (positive→bullish, negative→bearish, neutral→neutral; mixed→
      neutral with original preserved in producer_context).
    - **news ``magnitude`` (str|float) → contracts ``Magnitude`` (float)**
      via ``_coerce_magnitude`` (numeric passthrough; high/medium/low
      string proxy; unknown string raises).
    - **evidence_spans → canonical evidence ref strings**
      (``{article_id}#{locator}:{start_char}-{end_char}``); full
      ``EvidenceSpan`` objects preserved in
      ``producer_context.evidence_spans_detail``.
    """

    if ex_type not in {"Ex-1", "Ex-2", "Ex-3"}:
        raise ContractViolationError(
            f"_normalize_for_sdk only supports Ex-1/Ex-2/Ex-3; got {ex_type!r}"
        )

    evidence_spans_local = list(local_payload.get("evidence_spans") or [])
    evidence_refs = [_serialize_evidence_ref(span) for span in evidence_spans_local]
    produced_at = _now_iso()

    if ex_type == "Ex-1":
        involved_entities = list(local_payload.get("involved_entities") or [])
        primary_entity = involved_entities[0] if involved_entities else None
        producer_context: dict[str, Any] = {
            "article_id": local_payload.get("article_id"),
            "cluster_id": local_payload.get("cluster_id"),
            "summary": local_payload.get("summary"),
            "involved_entities": involved_entities,
            "event_time": local_payload.get("event_time"),
            "source_reliability_tier": local_payload.get(
                "source_reliability_tier"
            ),
            "evidence_spans_detail": evidence_spans_local,
            "export_contract": local_payload.get("export_contract"),
        }
        # Ex-1 emits the FIRST involved entity as canonical entity_id at
        # the wire boundary. Per CLAUDE.md #6 it MUST be resolved (the
        # full involved_entities list — including any unresolved /
        # ambiguous siblings — is preserved in producer_context for
        # audit). Ex-1 candidates with an unresolved primary entity must
        # be filtered upstream of _normalize_for_sdk; we fail-fast here
        # rather than fabricate an UNRESOLVED:* synthetic ID.
        return {
            # SDK envelope routing — stripped before contracts
            # model_validate and again before backend dispatch.
            "ex_type": "Ex-1",
            "subsystem_id": MODULE_ID,
            "fact_id": local_payload["candidate_id"],
            "entity_id": _require_canonical_id(
                primary_entity, role="entity_id"
            ),
            "fact_type": str(local_payload["fact_type"]),
            "fact_content": {
                "summary": local_payload.get("summary"),
                "event_time": local_payload.get("event_time"),
            },
            "confidence": float(local_payload["confidence"]),
            # contracts.Ex1.source_reference is REQUIRED top-level.
            "source_reference": dict(local_payload["source_reference"]),
            # news has no extracted_at; stamp at submit time.
            "extracted_at": produced_at,
            "evidence": evidence_refs,
            "producer_context": producer_context,
            "produced_at": produced_at,
        }

    if ex_type == "Ex-2":
        affected = list(local_payload.get("affected_entities") or [])
        # Per CLAUDE.md #6 every entity emitted at the canonical
        # affected_entities wire field MUST be resolved. Full
        # InvolvedEntity objects are preserved in
        # producer_context.affected_entities for audit/replay.
        affected_ids = [
            _require_canonical_id(entity, role=f"affected_entities[{idx}]")
            for idx, entity in enumerate(affected)
        ]
        direction_local = str(local_payload.get("direction", ""))
        try:
            direction_canonical = _NEWS_DIRECTION_TO_CONTRACTS_DIRECTION[
                direction_local
            ]
        except KeyError as exc:
            raise ContractViolationError(
                f"unknown news Direction value {direction_local!r}; expected "
                f"one of {sorted(_NEWS_DIRECTION_TO_CONTRACTS_DIRECTION)}"
            ) from exc
        producer_context = {
            "article_id": local_payload.get("article_id"),
            "cluster_id": local_payload.get("cluster_id"),
            "source_reference": dict(
                local_payload.get("source_reference") or {}
            ),
            "impact_scope": local_payload.get("impact_scope"),
            "rationale": local_payload.get("rationale"),
            "affected_entities": affected,  # full InvolvedEntity objects
            "evidence_spans_detail": evidence_spans_local,
            "export_contract": local_payload.get("export_contract"),
        }
        # Preserve news's "mixed" direction in producer_context (lossy
        # canonical mapping requires audit-trail recovery path).
        if direction_local == "mixed":
            producer_context["original_direction"] = direction_local
        return {
            "ex_type": "Ex-2",
            "subsystem_id": MODULE_ID,
            "signal_id": local_payload["candidate_id"],
            "signal_type": str(local_payload["signal_type"]),
            "direction": direction_canonical,
            "magnitude": _coerce_magnitude(local_payload["magnitude"]),
            "affected_entities": affected_ids,
            # contracts v0.1.3 allows []. News operates at article level,
            # not sector; sector enrichment is graph-engine downstream.
            "affected_sectors": [],
            "time_horizon": str(local_payload["time_horizon"]),
            "evidence": evidence_refs,
            "confidence": float(local_payload["confidence"]),
            "producer_context": producer_context,
            "produced_at": produced_at,
        }

    # Ex-3
    subject = local_payload.get("subject_entity") or {}
    obj = local_payload.get("object_entity") or {}
    producer_context = {
        "article_id": local_payload.get("article_id"),
        "source_reference": dict(
            local_payload.get("source_reference") or {}
        ),
        "subject_entity": subject,  # full InvolvedEntity
        "object_entity": obj,  # full InvolvedEntity
        "valid_from": local_payload.get("valid_from"),
        "requires_manual_review": local_payload.get("requires_manual_review"),
        # contracts.Ex3 has no canonical confidence slot — preserve here
        # for downstream Layer B replay/audit.
        "confidence": float(local_payload["confidence"]),
        "evidence_spans_detail": evidence_spans_local,
        "export_contract": local_payload.get("export_contract"),
    }
    return {
        "ex_type": "Ex-3",
        "subsystem_id": MODULE_ID,
        "delta_id": local_payload["candidate_id"],
        # news DeltaAction (add/update/deactivate) is meaningful enough
        # for Layer B routing; pass through directly (contracts.Ex3
        # delta_type is `str` with no enum constraint).
        "delta_type": str(local_payload["delta_action"]),
        # Per CLAUDE.md #6 source_node / target_node MUST be canonical
        # entity_ids. ``_require_graph_fields`` already rejects Ex-3
        # candidates with unresolved subject/object earlier in
        # ``_validate_candidate``; this is the wire-boundary
        # belt-and-suspenders check (defends against direct
        # ``_normalize_for_sdk`` callers that bypass _validate_candidate).
        "source_node": _require_canonical_id(subject, role="source_node"),
        "target_node": _require_canonical_id(obj, role="target_node"),
        "relation_type": str(local_payload["relation_type"]),
        "properties": {},
        "evidence": evidence_refs,
        "producer_context": producer_context,
        "produced_at": produced_at,
    }


def default_news_subsystem_context(*, backend: Any | None = None) -> Any:
    """Build a ready-to-use ``BaseSubsystemContext`` for news.

    Stage 2.9 follow-up #2 (codex review #2 P2): the CLI / orchestrator
    non-dry-run path requires a wired SDK runtime. This helper builds
    a context with sensible defaults so callers can do::

        with configure_runtime(default_news_subsystem_context()):
            run_once(config, sdk_client=DefaultSubsystemSdkClient())

    Default ``backend=None`` → ``MockSubmitBackend`` (in-memory, no
    Layer B contact). This is suitable for development / smoke /
    end-to-end testing where backend wiring is not yet productionized.
    Real Lite-PG / Full-Kafka backends are phase-4 work per
    CLAUDE.md §21; pass them explicitly when they exist.

    Returned as ``Any`` to keep this helper importable from CLI without
    forcing subsystem-sdk into the eager import graph (the actual
    type is ``subsystem_sdk.base.context.BaseSubsystemContext``).
    """

    from subsystem_sdk.backends.heartbeat import (
        SubmitBackendHeartbeatAdapter,
    )
    from subsystem_sdk.backends.mock import MockSubmitBackend
    from subsystem_sdk.base import (
        BaseSubsystemContext,
        SubsystemRegistrationSpec,
    )
    from subsystem_sdk.heartbeat.client import HeartbeatClient
    from subsystem_sdk.submit.client import SubmitClient

    if backend is None:
        backend = MockSubmitBackend()
    registration = SubsystemRegistrationSpec(
        subsystem_id=MODULE_ID,
        version=_NEWS_VERSION,
        domain="news",
        supported_ex_types=["Ex-0", "Ex-1", "Ex-2", "Ex-3"],
        owner="subsystem-news",
        heartbeat_policy_ref="interval:60s",
    )
    return BaseSubsystemContext(
        registration=registration,
        submit_client=SubmitClient(backend),
        heartbeat_client=HeartbeatClient(SubmitBackendHeartbeatAdapter(backend)),
    )


def _validated_payload(candidate: CandidatePayload) -> dict[str, Any]:
    """Run news-local revalidation then map to canonical wire shape.

    This is the single boundary news code goes through to produce a
    payload acceptable to ``subsystem_sdk.SubmitClient.submit`` (which
    in turn passes it to ``contracts.Ex*.model_validate`` via SDK
    ``validate_payload``). Use this in adapters / smoke / integration —
    do NOT call ``candidate.model_dump()`` directly into the SDK; the
    raw dump is news-local shape and contracts will reject it.
    """

    revalidated = _validate_candidate(candidate)
    if isinstance(revalidated, NewsFactCandidate):
        ex_type = "Ex-1"
    elif isinstance(revalidated, NewsSignalCandidate):
        ex_type = "Ex-2"
    elif isinstance(revalidated, NewsGraphDeltaCandidate):
        ex_type = "Ex-3"
    else:  # pragma: no cover - guarded by _validate_candidate
        raise ContractViolationError(
            "validated candidate is not a known News*Candidate"
        )
    return _normalize_for_sdk(revalidated.model_dump(mode="json"), ex_type)
