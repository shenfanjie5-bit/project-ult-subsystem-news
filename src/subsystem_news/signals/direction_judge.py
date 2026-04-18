"""Structured Ex-2 semantic judgement through reasoner-runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from subsystem_news.contracts.candidates import NewsFactCandidate, NewsSignalCandidate
from subsystem_news.contracts.taxonomy import Direction, ImpactScope, SignalType, TimeHorizon
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.runtime_client import (
    ReasonerRuntimeClient,
    StructuredGenerationRequest,
)
from subsystem_news.extract.schema_pin import SchemaPin
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN


_SIGNAL_JUDGEMENT_PROMPT = """\
Judge Ex-2 signal semantics for one locally validated Ex-1 news fact.
Use only the supplied fact summary, evidence quotes, and entity resolution statuses.
Do not invent canonical entities or fill missing evidence. Return one object under
judgement with signal_type, direction, impact_scope, time_horizon, rationale, and
confidence."""

_JUDGEMENT_FIELDS = frozenset(
    {
        "signal_type",
        "direction",
        "impact_scope",
        "time_horizon",
        "rationale",
        "confidence",
    }
)


class SignalJudgement(BaseModel):
    """Runtime semantic judgement needed to build an Ex-2 signal candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_type: SignalType
    direction: Direction
    impact_scope: ImpactScope
    time_horizon: TimeHorizon
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


def judge_direction(
    fact: NewsFactCandidate,
    client: ReasonerRuntimeClient,
    *,
    schema_pin: SchemaPin = SIGNAL_SCHEMA_PIN,
) -> SignalJudgement:
    """Ask reasoner-runtime for direction, scope, horizon, and rationale."""

    request = _build_signal_judgement_request(fact, schema_pin=schema_pin)
    response = client.generate_structured(request)
    draft = _judgement_draft(response)
    payload = _judgement_payload(draft)

    try:
        return SignalJudgement.model_validate(payload)
    except ValidationError as exc:
        raise ContractViolationError(
            "runtime signal judgement violates required Ex-2 semantic fields"
        ) from exc


def _build_signal_judgement_request(
    fact: NewsFactCandidate,
    *,
    schema_pin: SchemaPin,
) -> StructuredGenerationRequest:
    _require_signal_schema_pin(schema_pin)
    return StructuredGenerationRequest(
        schema_name=schema_pin.schema_name,
        schema_version=schema_pin.schema_version,
        contract=schema_pin.contract,
        model_output_version=schema_pin.model_output_version,
        response_schema=NewsSignalCandidate.model_json_schema(),
        prompt=_SIGNAL_JUDGEMENT_PROMPT,
        input_payload={
            "schema_pin": schema_pin.model_dump(mode="json"),
            "fact": {
                "candidate_id": fact.candidate_id,
                "article_id": fact.article_id,
                "cluster_id": fact.cluster_id,
                "fact_type": fact.fact_type,
                "summary": fact.summary,
                "event_time": fact.event_time.isoformat()
                if fact.event_time is not None
                else None,
                "confidence": fact.confidence,
                "source_reliability_tier": fact.source_reliability_tier,
                "source_reference": fact.source_reference.model_dump(mode="json"),
            },
            "evidence_quotes": [
                {
                    "article_id": span.article_id,
                    "locator": span.locator,
                    "start_char": span.start_char,
                    "end_char": span.end_char,
                    "quote": span.quote,
                }
                for span in fact.evidence_spans
            ],
            "entity_resolution_statuses": [
                {
                    "mention_text": entity.mention_text,
                    "canonical_id": entity.canonical_id,
                    "resolution_status": entity.resolution_status,
                    "type_hint": entity.type_hint,
                }
                for entity in fact.involved_entities
            ],
        },
    )


def _require_signal_schema_pin(schema_pin: SchemaPin) -> None:
    for field_name in ("contract", "schema_name", "schema_version", "model_output_version"):
        if getattr(schema_pin, field_name) != getattr(SIGNAL_SCHEMA_PIN, field_name):
            raise ContractViolationError(
                "Ex-2 signal judgement requires SIGNAL_SCHEMA_PIN; "
                f"{field_name}={getattr(schema_pin, field_name)!r}"
            )


def _judgement_draft(response: Mapping[str, object]) -> Mapping[str, object]:
    for key in (
        "judgement",
        "signal_judgement",
        "signal",
        "signal_candidate",
        "candidate",
    ):
        raw = response.get(key)
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise ContractViolationError(f"runtime response field {key} must be a mapping")
        return raw

    for key in ("signals", "signal_candidates", "candidates"):
        raw_signals = response.get(key)
        if raw_signals is None:
            continue
        if not isinstance(raw_signals, Sequence) or isinstance(raw_signals, str | bytes):
            raise ContractViolationError(f"runtime response field {key} must be a list")
        if not raw_signals:
            raise ContractViolationError(f"runtime response field {key} must not be empty")
        first = raw_signals[0]
        if not isinstance(first, Mapping):
            raise ContractViolationError("runtime signal draft must be a mapping")
        return first

    if _JUDGEMENT_FIELDS <= set(response.keys()):
        return response

    raise ContractViolationError("runtime response missing signal judgement")


def _judgement_payload(draft: Mapping[str, object]) -> dict[str, object]:
    missing = [field for field in _JUDGEMENT_FIELDS if field not in draft]
    if missing:
        raise ContractViolationError(
            f"runtime signal judgement missing fields: {', '.join(sorted(missing))}"
        )
    return {field: draft[field] for field in _JUDGEMENT_FIELDS}


__all__ = ["SignalJudgement", "judge_direction"]
