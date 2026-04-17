from __future__ import annotations

from subsystem_news.normalize.text_clean import clean_text, detect_language, normalize_title


def test_clean_text_collapses_whitespace_entities_and_controls() -> None:
    text = "\ufeff Acme&nbsp;Corp\n\tannounced \x00 a 订单。 "

    assert clean_text(text) == "Acme Corp announced a 订单。"


def test_normalize_title_handles_missing_and_entities() -> None:
    assert normalize_title(None) == ""
    assert normalize_title("  Acme &amp; Globex  ") == "Acme & Globex"


def test_detect_language_prefers_source_language_then_infers() -> None:
    assert detect_language("Title", "Body", "ZH-CN") == "zh-cn"
    assert detect_language("订单", "公司获得新的订单") == "zh"
    assert detect_language("Acme signs deal", "The company announced a contract.") == "en"
