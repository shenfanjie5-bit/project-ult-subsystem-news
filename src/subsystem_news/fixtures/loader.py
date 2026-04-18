"""Regression fixture manifest loading and validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.errors import ContractViolationError
from subsystem_news.fixtures.catalog import FixtureCase, FixtureSuite


DEFAULT_REGRESSION_MANIFEST = Path(__file__).parent / "regression" / "manifest.json"


def load_fixture_suite(root: Path | None = None) -> FixtureSuite:
    """Load and validate a regression fixture suite manifest."""

    manifest_path = _manifest_path(root)
    try:
        suite = FixtureSuite.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ContractViolationError("fixture manifest violates FixtureSuite") from exc
    suite = suite.model_copy(
        update={
            "manifest_path": manifest_path,
            "root_path": manifest_path.parent,
        }
    )
    return validate_fixture_suite(suite)


def validate_fixture_suite(suite: FixtureSuite) -> FixtureSuite:
    """Validate cross-case fixture invariants."""

    seen_candidate_ids: set[str] = set()
    for case in suite.cases:
        _validate_case_articles(case)
        _validate_case_sources(case)
        for output in case.expected_outputs:
            if output.candidate_id in seen_candidate_ids:
                raise ContractViolationError(
                    f"duplicate expected candidate ID: {output.candidate_id}"
                )
            seen_candidate_ids.add(output.candidate_id)
            _validate_expected_output(
                case,
                candidate_id=output.candidate_id,
                article_id=output.article_id,
                source_reference=output.source_reference,
                output_article_ids=set(case.article_ids),
            )
            for span in output.evidence_spans:
                _validate_evidence_quote(case, span)
    return suite


def _manifest_path(root: Path | None) -> Path:
    if root is None:
        return DEFAULT_REGRESSION_MANIFEST
    path = Path(root)
    if path.is_dir():
        return path / "manifest.json"
    return path


def _validate_case_articles(case: FixtureCase) -> None:
    raw_ids = {raw.article_id for raw in case.raw_inputs}
    artifact_ids = {artifact.article_id for artifact in case.normalized_artifacts}
    declared = set(case.article_ids)
    unknown_raw = raw_ids - declared
    unknown_artifacts = artifact_ids - declared
    if unknown_raw:
        raise ContractViolationError(
            f"{case.case_id} raw input article_id not declared: "
            f"{', '.join(sorted(unknown_raw))}"
        )
    if unknown_artifacts:
        raise ContractViolationError(
            f"{case.case_id} normalized artifact article_id not declared: "
            f"{', '.join(sorted(unknown_artifacts))}"
        )


def _validate_case_sources(case: FixtureCase) -> None:
    references = _article_source_references(case)
    if references and _source_ref_key(case.source_reference) not in references:
        raise ContractViolationError(
            f"{case.case_id} source_reference must match a raw input or normalized artifact"
        )
    for artifact in case.normalized_artifacts:
        if artifact.source_reference.source_id != artifact.source_id:
            raise ContractViolationError(
                f"{case.case_id} artifact source_reference.source_id mismatch"
            )


def _validate_expected_output(
    case: FixtureCase,
    *,
    candidate_id: str,
    article_id: str,
    source_reference: SourceReference,
    output_article_ids: set[str],
) -> None:
    known_refs = _known_source_references(case)
    if article_id not in output_article_ids:
        raise ContractViolationError(
            f"{case.case_id} expected output article_id not declared: {article_id}"
        )
    source_key = _source_ref_key(source_reference)
    article_refs = _article_source_references_for(case, article_id)
    if article_refs and source_key not in article_refs:
        raise ContractViolationError(
            f"{case.case_id} expected output source_reference does not match "
            f"article_id: {candidate_id}"
        )
    if source_key not in known_refs:
        raise ContractViolationError(
            f"{case.case_id} expected output source_reference is not part of case: "
            f"{candidate_id}"
        )


def _validate_evidence_quote(case: FixtureCase, span: EvidenceSpan) -> None:
    artifact = next(
        (
            candidate
            for candidate in case.normalized_artifacts
            if candidate.article_id == span.article_id
        ),
        None,
    )
    if artifact is None:
        raise ContractViolationError(
            f"{case.case_id} evidence article_id has no normalized artifact: "
            f"{span.article_id}"
        )

    text = artifact.title if span.locator == "title" else artifact.body_text
    if span.end_char > len(text):
        raise ContractViolationError(
            f"{case.case_id} evidence span is out of bounds: {span.article_id}"
        )
    if text[span.start_char : span.end_char] != span.quote:
        raise ContractViolationError(
            f"{case.case_id} evidence quote does not match normalized artifact: "
            f"{span.article_id}"
        )


def _known_source_references(case: FixtureCase) -> set[tuple[str, str | None, str | None]]:
    refs = _article_source_references(case)
    refs.add(_source_ref_key(case.source_reference))
    return refs


def _article_source_references(
    case: FixtureCase,
) -> set[tuple[str, str | None, str | None]]:
    refs = {_source_ref_key(raw.source_reference) for raw in case.raw_inputs}
    refs.update(_source_ref_key(artifact.source_reference) for artifact in case.normalized_artifacts)
    return refs


def _article_source_references_for(
    case: FixtureCase,
    article_id: str,
) -> set[tuple[str, str | None, str | None]]:
    refs = {
        _source_ref_key(raw.source_reference)
        for raw in case.raw_inputs
        if raw.article_id == article_id
    }
    refs.update(
        _source_ref_key(artifact.source_reference)
        for artifact in case.normalized_artifacts
        if artifact.article_id == article_id
    )
    return refs


def _source_ref_key(reference: SourceReference) -> tuple[str, str | None, str | None]:
    url = str(reference.url) if reference.url is not None else None
    return (reference.source_id, url, reference.provider_key)


__all__ = [
    "DEFAULT_REGRESSION_MANIFEST",
    "load_fixture_suite",
    "validate_fixture_suite",
]
