"""Stage 2.9 contract tier — runtime contract signature stability.

This file checks news's PUBLIC API surface (the symbols subsystem-news
exposes to other modules + assembly) doesn't drift in shape:

- Public entrypoint singletons present + correct method signatures.
- Canonical mapper signature stable.
- Submit boundary classes + helpers present.

Iron rule #4: tests/contract/ MUST contain real tests (no empty
``__init__.py``-only directory). This file is the SDK-independent
contract baseline; ``test_contracts_alignment.py`` adds the cross-repo
``contracts.Ex*`` round-trip on top.
"""

from __future__ import annotations

import inspect

import pytest


class TestPublicEntrypointSingletons:
    """The 5 module-level singleton instances assembly references."""

    def test_module_level_singletons_present(self) -> None:
        from subsystem_news import public

        for name in (
            "health_probe",
            "smoke_hook",
            "init_hook",
            "version_declaration",
            "cli",
        ):
            assert hasattr(public, name), f"public.{name} missing"
            assert public.__all__.count(name) == 1

    def test_health_probe_check_signature(self) -> None:
        from subsystem_news.public import health_probe

        sig = inspect.signature(health_probe.check)
        assert list(sig.parameters) == ["timeout_sec"]
        param = sig.parameters["timeout_sec"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty
        # public.py uses `from __future__ import annotations` so
        # annotations are stringified at parse time.
        assert str(param.annotation) == "float"

    def test_smoke_hook_run_signature(self) -> None:
        from subsystem_news.public import smoke_hook

        sig = inspect.signature(smoke_hook.run)
        assert list(sig.parameters) == ["profile_id"]
        param = sig.parameters["profile_id"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty
        assert str(param.annotation) == "str"

    def test_init_hook_initialize_signature(self) -> None:
        from subsystem_news.public import init_hook

        sig = inspect.signature(init_hook.initialize)
        assert list(sig.parameters) == ["resolved_env"]
        param = sig.parameters["resolved_env"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty

    def test_version_declaration_declare_signature(self) -> None:
        from subsystem_news.public import version_declaration

        sig = inspect.signature(version_declaration.declare)
        assert list(sig.parameters) == []  # no parameters except self

    def test_cli_invoke_signature(self) -> None:
        from subsystem_news.public import cli

        sig = inspect.signature(cli.invoke)
        assert list(sig.parameters) == ["argv"]
        param = sig.parameters["argv"]
        assert param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert param.default is inspect.Parameter.empty


class TestCanonicalMapperSignature:
    """Canonical mapper + production helpers signature stability."""

    def test_normalize_for_sdk_signature(self) -> None:
        from subsystem_news.runtime.submit import _normalize_for_sdk

        sig = inspect.signature(_normalize_for_sdk)
        assert list(sig.parameters) == ["local_payload", "ex_type"]

    def test_validated_payload_signature(self) -> None:
        from subsystem_news.runtime.submit import _validated_payload

        sig = inspect.signature(_validated_payload)
        assert list(sig.parameters) == ["candidate"]

    def test_module_id_constant(self) -> None:
        from subsystem_news.runtime.submit import MODULE_ID

        assert MODULE_ID == "subsystem-news"


class TestSubmitBoundarySymbols:
    """Submit boundary classes + helpers stable surface."""

    def test_submit_receipt_required_fields(self) -> None:
        from subsystem_news.runtime.submit import SubmitReceipt

        for field in (
            "accepted_count",
            "rejected_count",
            "submitted_candidate_ids",
            "rejected_candidate_ids",
            "receipt_id",
        ):
            assert field in SubmitReceipt.model_fields, (
                f"SubmitReceipt missing {field!r}"
            )

    def test_subsystem_sdk_client_protocol(self) -> None:
        from subsystem_news.runtime.submit import (
            DefaultSubsystemSdkClient,
            SubsystemSdkClient,
        )

        # DefaultSubsystemSdkClient must satisfy the protocol.
        assert hasattr(DefaultSubsystemSdkClient, "submit")
        assert hasattr(SubsystemSdkClient, "submit")

    def test_validate_candidate_batch_present(self) -> None:
        from subsystem_news.runtime.submit import validate_candidate_batch

        sig = inspect.signature(validate_candidate_batch)
        assert list(sig.parameters) == ["batch"]

    def test_submit_candidates_present(self) -> None:
        from subsystem_news.runtime.submit import submit_candidates

        sig = inspect.signature(submit_candidates)
        assert "batch" in sig.parameters
        assert "client" in sig.parameters
        assert "max_retries" in sig.parameters


class TestCandidateModelSurface:
    """Frozen Pydantic models — public Ex-1/2/3 candidate types stable."""

    def test_news_fact_candidate_required_fields(self) -> None:
        from subsystem_news.contracts.candidates import NewsFactCandidate

        for field in (
            "candidate_id",
            "article_id",
            "fact_type",
            "summary",
            "involved_entities",
            "confidence",
            "source_reliability_tier",
            "source_reference",
            "evidence_spans",
            "export_contract",
        ):
            assert field in NewsFactCandidate.model_fields

    def test_news_signal_candidate_required_fields(self) -> None:
        from subsystem_news.contracts.candidates import NewsSignalCandidate

        for field in (
            "candidate_id",
            "article_id",
            "signal_type",
            "direction",
            "magnitude",
            "affected_entities",
            "impact_scope",
            "time_horizon",
            "confidence",
            "source_reference",
            "evidence_spans",
            "export_contract",
        ):
            assert field in NewsSignalCandidate.model_fields

    def test_news_graph_delta_candidate_required_fields(self) -> None:
        from subsystem_news.contracts.candidates import (
            NewsGraphDeltaCandidate,
        )

        for field in (
            "candidate_id",
            "article_id",
            "subject_entity",
            "relation_type",
            "object_entity",
            "delta_action",
            "confidence",
            "requires_manual_review",
            "source_reference",
            "evidence_spans",
            "export_contract",
        ):
            assert field in NewsGraphDeltaCandidate.model_fields
