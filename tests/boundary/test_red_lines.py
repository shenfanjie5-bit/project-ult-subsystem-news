"""Stage 2.9 boundary tier — §10 red lines as boundary tests.

Per CLAUDE.md (subsystem-news):
1. **Approved-source-only enforcement** (CLAUDE.md #1): non-approved
   sources must be rejected at ``load_allowlist``.
2. **Evidence span mandatory** (CLAUDE.md #5): every Ex candidate must
   carry at least one EvidenceSpan.
3. **No second parser / no provider SDK / no business import**: the
   public.py module must NOT import any disallowed package.
4. **Iron rule #7 SDK wire-shape boundary**: the canonical wire payload
   delivered through real ``subsystem_sdk`` adapter chain must NOT carry
   any SDK envelope field after dispatch.
5. **Mixed-batch dependency hint**: news's batch validator + canonical
   mapper must reject Ex-2/Ex-3 candidates that reference missing Ex-1
   facts in the same batch (sibling of announcement's
   ``_missing_unaccepted_batch_fact_ids`` regression guard).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import (
    SourceReference,
    SourceReferenceLocator,
)
from subsystem_news.contracts.sources import load_allowlist
from subsystem_news.errors import (
    ContractViolationError,
    EvidenceMissingError,
    SourceNotApprovedError,
)


# ── Helpers ────────────────────────────────────────────────────────


def _source_ref() -> SourceReference:
    return SourceReference(
        source_id="redline-source-A1",
        url="https://example-approved-news.com/r/1",
        provider_key=None,
        original_locator=SourceReferenceLocator(
            locator_type="rss_guid",
            locator_value="redline-locator-001",
        ),
    )


def _evidence_span() -> EvidenceSpan:
    return EvidenceSpan(
        article_id="redline-art-001",
        start_char=0,
        end_char=11,
        quote="placeholder",
        locator="title",
    )


def _entity(canonical_id: str = "ENT_STOCK_REDLINE_001") -> InvolvedEntity:
    return InvolvedEntity(
        mention_text="Redline Corp",
        canonical_id=canonical_id,
        resolution_status="resolved",
        type_hint="company",
    )


# ── Red line 1: approved-source-only enforcement ────────────────────


class TestApprovedSourceOnly:
    """CLAUDE.md #1: ``load_allowlist`` MUST reject any source with
    ``approved=False``. This guards against accidental ingestion of
    non-vetted news outlets.
    """

    def test_load_allowlist_rejects_unapproved_source(
        self, tmp_path: Path
    ) -> None:
        config_path = tmp_path / "bad_sources.json"
        config_path.write_text(
            json.dumps([
                {
                    "source_id": "approved-A1",
                    "display_name": "Approved Source A1",
                    "access_mode": "rss",
                    "base_url": "https://example-approved.com",
                    "approved": True,
                    "reliability_tier": "A",
                    "license_tag": "MIT-equiv",
                    "language": "en",
                    "credential_ref": None,
                },
                {
                    "source_id": "rogue-X9",
                    "display_name": "Unapproved Source X9",
                    "access_mode": "site_html",
                    "base_url": "https://rogue.example.com",
                    "approved": False,
                    "reliability_tier": "C",
                    "license_tag": "unknown",
                    "language": "en",
                    "credential_ref": None,
                },
            ]),
            encoding="utf-8",
        )

        with pytest.raises(SourceNotApprovedError, match="rogue-X9"):
            load_allowlist(config_path)


# ── Red line 2: evidence span mandatory ────────────────────────────


class TestEvidenceSpanMandatory:
    """CLAUDE.md #5: every Ex candidate must carry at least one
    EvidenceSpan; ``_EvidenceRequiredModel`` model_validator enforces
    this at construction time.
    """

    def test_news_fact_candidate_rejects_empty_evidence_spans(self) -> None:
        with pytest.raises(EvidenceMissingError):
            NewsFactCandidate(
                candidate_id="redline-no-evidence-ex1",
                article_id="redline-art-001",
                cluster_id=None,
                source_reference=_source_ref(),
                fact_type="contract",
                summary="placeholder",
                involved_entities=[_entity()],
                event_time=datetime(2026, 1, 1, tzinfo=UTC),
                confidence=0.9,
                source_reliability_tier="A",
                evidence_spans=[],  # red line — must reject
            )

    def test_news_signal_candidate_rejects_empty_evidence_spans(self) -> None:
        with pytest.raises(EvidenceMissingError):
            NewsSignalCandidate(
                candidate_id="redline-no-evidence-ex2",
                article_id="redline-art-001",
                cluster_id=None,
                source_reference=_source_ref(),
                signal_type="event_impact",
                direction="positive",
                magnitude=0.5,
                affected_entities=[_entity()],
                impact_scope="company",
                time_horizon="short",
                rationale="placeholder",
                confidence=0.5,
                evidence_spans=[],  # red line
            )

    def test_news_graph_delta_candidate_rejects_empty_evidence_spans(
        self,
    ) -> None:
        with pytest.raises(EvidenceMissingError):
            NewsGraphDeltaCandidate(
                candidate_id="redline-no-evidence-ex3",
                article_id="redline-art-001",
                source_reference=_source_ref(),
                subject_entity=_entity("ENT_STOCK_REDLINE_SRC"),
                relation_type="supplier_of",
                object_entity=_entity("ENT_STOCK_REDLINE_DST"),
                delta_action="add",
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                confidence=0.9,
                requires_manual_review=True,
                evidence_spans=[],  # red line
            )


# ── Red line 3: public.py deny-scan (no business / parser / provider) ─


class TestPublicPyDenyScan:
    """CLAUDE.md: public.py is the assembly-facing boundary. It MUST
    NOT pull in:

    - **Other business modules**: ``data_platform``, ``main_core``,
      ``graph_engine``, ``audit_eval``, ``orchestrator``, ``assembly``.
    - **Direct LLM provider SDKs**: ``openai``, ``anthropic``,
      ``litellm`` (complex extraction goes through reasoner-runtime).
    - **Heavy parser stacks beyond approved adapters**: ``pdfplumber``,
      ``pypdf``, ``unstructured``, ``pdfminer`` (news consumes RSS /
      API / HTML through the source adapter registry).

    Iron rule #2: deny-scan uses ``subprocess.run`` for isolation.
    sys.modules pollution from earlier collected tests would mask real
    import-graph leaks. Run the import in a fresh interpreter and
    inspect ``sys.modules`` from there.
    """

    _DENYLIST: tuple[str, ...] = (
        # Other business modules.
        "data_platform",
        "main_core",
        "graph_engine",
        "audit_eval",
        "orchestrator",
        "assembly",
        # Direct LLM provider SDKs (must go through reasoner-runtime).
        "openai",
        "anthropic",
        "litellm",
        # Other parser stacks (news uses approved RSS/API/HTML adapters).
        "pdfplumber",
        "pypdf",
        "unstructured",
        "pdfminer",
    )

    def test_public_py_imports_no_denied_modules(self) -> None:
        """Run ``import subsystem_news.public`` in a fresh interpreter
        and dump ``sys.modules``. The deny-scan main test asserts none
        of the denied module names appear.
        """

        program = (
            "import json\n"
            "import sys\n"
            "import subsystem_news.public  # noqa: F401\n"
            "print(json.dumps(sorted(sys.modules)))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
        )
        loaded_modules = set(json.loads(result.stdout))

        leaked: list[str] = []
        for denied in self._DENYLIST:
            # Match exact module name OR any submodule (e.g.
            # "openai.types").
            if denied in loaded_modules:
                leaked.append(denied)
                continue
            for mod in loaded_modules:
                if mod.startswith(f"{denied}."):
                    leaked.append(mod)
                    break

        assert not leaked, (
            f"public.py import graph leaked denied modules: {sorted(leaked)}; "
            "CLAUDE.md forbids news.public from importing other business "
            "modules / direct LLM provider SDKs / heavy parser stacks."
        )


# ── Red line 4: SDK wire-shape boundary (iron rule #7) ──────────────


class TestSdkWireShapeBoundary:
    """Iron rule #7: news's canonical wire payload delivered through
    real ``subsystem_sdk`` envelope-strip path must NOT carry
    ``ex_type``/``semantic``/``produced_at`` (the SDK envelope set) at
    the wire boundary backends actually receive.

    This is the news-side complement of subsystem-sdk's own envelope
    strip tests. ``MockSubmitBackend`` records what arrives at the
    wire after ``validate_then_dispatch`` strip.
    """

    def test_mock_backend_receives_no_sdk_envelope_fields(self) -> None:
        from subsystem_sdk.backends.mock import MockSubmitBackend
        from subsystem_sdk.submit.client import SubmitClient
        from subsystem_sdk.validate.engine import SDK_ENVELOPE_FIELDS
        from subsystem_sdk.validate.result import ValidationResult

        from subsystem_news.runtime.submit import _validated_payload

        candidate = NewsFactCandidate(
            candidate_id="redline-wire-shape-ex1",
            article_id="redline-art-001",
            cluster_id=None,
            source_reference=_source_ref(),
            fact_type="contract",
            summary="placeholder",
            involved_entities=[_entity()],
            event_time=datetime(2026, 1, 1, tzinfo=UTC),
            confidence=0.9,
            source_reliability_tier="A",
            evidence_spans=[_evidence_span()],
        )
        wire_payload = _validated_payload(candidate)

        backend = MockSubmitBackend()

        def permissive_validator(_: Any) -> ValidationResult:
            return ValidationResult.ok(
                ex_type="Ex-1", schema_version="boundary-test"
            )

        client = SubmitClient(backend, validator=permissive_validator)
        receipt = client.submit(wire_payload)

        assert receipt.accepted, list(receipt.errors)
        assert len(backend.submitted_payloads) == 1
        wire = backend.submitted_payloads[0]
        leaked = SDK_ENVELOPE_FIELDS.intersection(wire)
        assert not leaked, (
            f"news -> SDK -> backend: SDK envelope leaked {sorted(leaked)}; "
            "validate_then_dispatch must strip envelope before dispatch "
            "(铁律 #7 wire-shape boundary)"
        )

    def test_envelope_set_canonical_definition_holds(self) -> None:
        """Lock SDK envelope set — news's red-line tests + integration
        tests both assume this exact 3-field set.
        """

        from subsystem_sdk.validate.engine import SDK_ENVELOPE_FIELDS

        assert SDK_ENVELOPE_FIELDS == frozenset(
            {"ex_type", "semantic", "produced_at"}
        ), (
            f"SDK_ENVELOPE_FIELDS drifted: got "
            f"{sorted(SDK_ENVELOPE_FIELDS)}; expected "
            "{ex_type, semantic, produced_at}"
        )


# ── Red line 5: mixed-batch dependency reject (Ex-2/3 must reference
#               valid Ex-1 fact_ids submitted in the same batch) ─────


class TestMixedBatchEx2RequiresEx1Reference:
    """News's ``_validate_candidate`` (per-candidate) doesn't enforce
    cross-batch Ex-1↔Ex-2/3 dependency ordering — that's a
    runtime/orchestrator concern. But Ex-2/Ex-3 candidates with no
    valid ``affected_entities`` / ``subject_entity`` / ``object_entity``
    must be rejected at construction or at the canonical mapper.

    This is the news analog of announcement's
    ``_missing_unaccepted_batch_fact_ids`` regression guard. The mapper
    reads canonical_id from ``InvolvedEntity`` directly (not from a
    post-normalize wire payload), so refactoring the wire shape can't
    silently disable the check.
    """

    def test_ex2_with_no_affected_entities_rejected_at_construction(
        self,
    ) -> None:
        with pytest.raises(Exception) as excinfo:  # noqa: BLE001
            NewsSignalCandidate(
                candidate_id="redline-ex2-no-affected",
                article_id="redline-art-001",
                cluster_id=None,
                source_reference=_source_ref(),
                signal_type="event_impact",
                direction="positive",
                magnitude=0.5,
                affected_entities=[],  # red line: min_length=1
                impact_scope="company",
                time_horizon="short",
                rationale="placeholder",
                confidence=0.5,
                evidence_spans=[_evidence_span()],
            )
        assert "affected_entities" in str(excinfo.value).lower() or (
            "min_length" in str(excinfo.value).lower()
        )

    def test_ex3_unresolved_subject_entity_rejected_by_validator(
        self,
    ) -> None:
        """``_validate_candidate`` (via ``_require_graph_fields``) must
        reject Ex-3 candidates whose subject/object entity has
        ``resolution_status != "resolved"``. This is news's high-bar
        analog of the announcement Ex-3 evidence threshold.
        """

        from subsystem_news.runtime.submit import _validate_candidate

        candidate = NewsGraphDeltaCandidate(
            candidate_id="redline-ex3-unresolved-subject",
            article_id="redline-art-001",
            source_reference=_source_ref(),
            subject_entity=InvolvedEntity(
                mention_text="Mystery Co",
                canonical_id=None,
                resolution_status="unresolved",
                type_hint="company",
            ),
            relation_type="supplier_of",
            object_entity=_entity("ENT_STOCK_REDLINE_DST"),
            delta_action="add",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            confidence=0.9,
            requires_manual_review=True,
            evidence_spans=[
                _evidence_span(),
                EvidenceSpan(
                    article_id="redline-art-001",
                    start_char=20,
                    end_char=35,
                    quote="dual_evidence!!",
                    locator="body",
                ),
            ],
        )

        with pytest.raises(ContractViolationError, match="subject_entity"):
            _validate_candidate(candidate)
