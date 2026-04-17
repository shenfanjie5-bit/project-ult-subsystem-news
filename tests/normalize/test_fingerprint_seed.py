from __future__ import annotations

from subsystem_news.normalize.fingerprint_seed import content_hash, fingerprint_seed


def test_content_hash_is_stable_for_same_text() -> None:
    text = "Acme Corp announced a contract."

    assert content_hash(text) == content_hash(text)
    assert content_hash(text).startswith("sha256:")


def test_fingerprint_seed_is_stable_across_whitespace_changes() -> None:
    title = "Acme signs contract"
    body_a = "Acme Corp announced a contract. Shipments start in 2026."
    body_b = " Acme Corp announced   a contract.\n\nShipments start in 2026. "

    assert fingerprint_seed(title, body_a) == fingerprint_seed(f"  {title} ", body_b)


def test_fingerprint_seed_changes_for_different_events() -> None:
    title = "Acme signs contract"
    body = "Acme Corp announced a contract. Shipments start in 2026."
    other_body = "Globex recalled battery modules after a plant fire."

    assert fingerprint_seed(title, body) != fingerprint_seed(title, other_body)
