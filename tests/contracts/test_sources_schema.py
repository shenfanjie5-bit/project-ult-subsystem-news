from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from subsystem_news.contracts.sources import NewsSourceConfig, load_allowlist
from subsystem_news.errors import ContractViolationError, SourceNotApprovedError


def valid_source_payload() -> dict[str, object]:
    return {
        "source_id": "global-wire-rss",
        "display_name": "Global Wire RSS",
        "access_mode": "rss",
        "base_url": "https://news.example.com/rss",
        "approved": True,
        "reliability_tier": "A",
        "license_tag": "licensed-wire",
        "language": "en",
        "credential_ref": None,
    }


def test_source_config_valid_sample_passes() -> None:
    config = NewsSourceConfig.model_validate(valid_source_payload())

    assert config.source_id == "global-wire-rss"
    assert config.access_mode == "rss"
    assert config.approved is True


@pytest.mark.parametrize("credential_ref", [None, "secret://news/market-filings"])
def test_source_config_accepts_null_or_secret_credential_ref(
    credential_ref: str | None,
) -> None:
    payload = valid_source_payload()
    payload["credential_ref"] = credential_ref

    config = NewsSourceConfig.model_validate(payload)

    assert config.credential_ref == credential_ref


def test_source_config_rejects_raw_credential_ref() -> None:
    payload = valid_source_payload()
    payload["credential_ref"] = "plain-api-key"

    with pytest.raises(ValidationError) as exc_info:
        NewsSourceConfig.model_validate(payload)

    assert "credential_ref" in str(exc_info.value)


def test_source_config_missing_required_field_rejected() -> None:
    payload = valid_source_payload()
    del payload["source_id"]

    with pytest.raises(ValidationError) as exc_info:
        NewsSourceConfig.model_validate(payload)

    assert "source_id" in str(exc_info.value)


def test_source_config_invalid_enum_rejected_with_allowed_values() -> None:
    payload = valid_source_payload()
    payload["access_mode"] = "crawler"

    with pytest.raises(ValidationError) as exc_info:
        NewsSourceConfig.model_validate(payload)

    message = str(exc_info.value)
    assert "rss" in message
    assert "api" in message
    assert "site_html" in message


def test_load_allowlist_returns_approved_configs(tmp_path: Path) -> None:
    path = tmp_path / "approved_sources.json"
    path.write_text(json.dumps([valid_source_payload()]), encoding="utf-8")

    configs = load_allowlist(path)

    assert len(configs) == 1
    assert configs[0].source_id == "global-wire-rss"


def test_load_allowlist_returns_checked_in_valid_fixture() -> None:
    fixture_path = Path("src/subsystem_news/fixtures/approved_sources.valid.sample.json")

    configs = load_allowlist(fixture_path)

    assert {config.source_id for config in configs} == {
        "global-wire-rss",
        "market-filings-api",
        "company-site-html",
    }
    assert all(config.approved for config in configs)


def test_load_allowlist_rejects_unapproved_config(tmp_path: Path) -> None:
    payload = valid_source_payload()
    payload["source_id"] = "unapproved-blog"
    payload["approved"] = False
    path = tmp_path / "unapproved_sources.json"
    path.write_text(json.dumps([payload]), encoding="utf-8")

    with pytest.raises(SourceNotApprovedError) as exc_info:
        load_allowlist(path)

    assert "unapproved-blog" in str(exc_info.value)


def test_load_allowlist_rejects_invalid_fixture_raw_credential() -> None:
    fixture_path = Path("src/subsystem_news/fixtures/approved_sources.invalid.sample.json")

    with pytest.raises(ContractViolationError) as exc_info:
        load_allowlist(fixture_path)

    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_load_allowlist_wraps_schema_violation(tmp_path: Path) -> None:
    payload = valid_source_payload()
    del payload["base_url"]
    path = tmp_path / "invalid_sources.json"
    path.write_text(json.dumps([payload]), encoding="utf-8")

    with pytest.raises(ContractViolationError) as exc_info:
        load_allowlist(path)

    assert isinstance(exc_info.value.__cause__, ValidationError)
