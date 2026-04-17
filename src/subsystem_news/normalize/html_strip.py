"""Lightweight HTML boilerplate stripping for article bodies."""

from __future__ import annotations

from html.parser import HTMLParser

from subsystem_news.normalize.text_clean import clean_text


_SKIP_TAGS = {
    "aside",
    "footer",
    "form",
    "header",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
}
_BLOCK_TAGS = {
    "article",
    "blockquote",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "main",
    "p",
    "section",
    "td",
    "th",
    "tr",
}


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_stack: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in _SKIP_TAGS:
            self._skip_stack.append(normalized_tag)
            return
        if self._skip_stack:
            return
        if self._is_hidden(attrs):
            self._skip_stack.append(normalized_tag)
            return
        if normalized_tag in _BLOCK_TAGS:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if self._skip_stack:
            if normalized_tag == self._skip_stack[-1]:
                self._skip_stack.pop()
            return
        if normalized_tag in _BLOCK_TAGS:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_stack:
            self._parts.append(data)

    @staticmethod
    def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
        for name, value in attrs:
            normalized_name = name.lower()
            normalized_value = (value or "").lower()
            if normalized_name == "hidden":
                return True
            if normalized_name == "aria-hidden" and normalized_value == "true":
                return True
            if normalized_name == "style" and "display:none" in normalized_value.replace(" ", ""):
                return True
        return False

    def text(self) -> str:
        return "".join(self._parts)


def strip_boilerplate(html: str) -> str:
    """Extract visible article text using only the Python standard library."""

    parser = _ArticleTextParser()
    parser.feed(html)
    parser.close()
    return clean_text(parser.text())
