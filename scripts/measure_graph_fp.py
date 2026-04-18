"""Measure Ex-3 false positives over curated graph fixtures."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import InvolvedEntity, NewsFactCandidate
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference, SourceReferenceLocator
from subsystem_news.entities.mention import Mention
from subsystem_news.entities.resolution import EntityResolutionResult, ResolvedMention
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.graph import extract_graph_deltas


class _FixtureRuntimeClient:
    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = response
        self.requests: list[StructuredGenerationRequest] = []

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        self.requests.append(request)
        return self.response


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive", required=True, type=Path)
    parser.add_argument("--negative", required=True, type=Path)
    parser.add_argument("--max-fp-rate", type=float, default=0.01)
    args = parser.parse_args(argv)

    positives = _load_cases(args.positive)
    negatives = _load_cases(args.negative)
    positive_results = [_run_case(case) for case in positives]
    negative_results = [_run_case(case) for case in negatives]

    positive_detected = sum(1 for result in positive_results if result["count"] > 0)
    false_positives = [
        result for result in negative_results if result["count"] > 0
    ]
    negative_total = len(negative_results)
    fp_rate = len(false_positives) / negative_total if negative_total else 0.0
    errors = [
        result
        for result in [*positive_results, *negative_results]
        if result["error"] is not None
    ]

    report = {
        "positive_total": len(positive_results),
        "positive_detected": positive_detected,
        "negative_total": negative_total,
        "false_positive_count": len(false_positives),
        "false_positive_rate": round(fp_rate, 6),
        "max_false_positive_rate": args.max_fp_rate,
        "false_positive_cases": [result["name"] for result in false_positives],
        "errors": errors,
    }
    print(json.dumps(report, sort_keys=True))

    if errors:
        return 1
    if positive_detected != len(positive_results):
        return 1
    if fp_rate > args.max_fp_rate:
        return 1
    return 0


def _load_cases(root: Path) -> list[Mapping[str, object]]:
    cases: list[Mapping[str, object]] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            raw_cases = payload
        elif isinstance(payload, Mapping) and isinstance(payload.get("cases"), list):
            raw_cases = payload["cases"]
        elif isinstance(payload, Mapping):
            raw_cases = [payload]
        else:
            raise ValueError(f"unsupported fixture payload: {path}")

        for raw_case in raw_cases:
            if not isinstance(raw_case, Mapping):
                raise ValueError(f"fixture case must be an object: {path}")
            cases.append(raw_case)
    return cases


def _run_case(case: Mapping[str, object]) -> dict[str, object]:
    name = str(case["name"])
    try:
        article, cluster, entity_resolution, facts, response = _build_case_models(case)
        candidates = extract_graph_deltas(
            article,
            cluster,
            entity_resolution,
            facts,
            _FixtureRuntimeClient(response),
        )
        return {"name": name, "count": len(candidates), "error": None}
    except Exception as exc:  # noqa: BLE001 - metrics need per-fixture error detail.
        return {"name": name, "count": 0, "error": f"{exc.__class__.__name__}: {exc}"}


def _build_case_models(
    case: Mapping[str, object],
) -> tuple[
    NewsArticleArtifact,
    NewsDedupeCluster,
    EntityResolutionResult,
    list[NewsFactCandidate],
    Mapping[str, object],
]:
    name = _safe_name(str(case["name"]))
    body_text = str(case["body_text"])
    title = str(case.get("title", body_text))
    locator = str(case.get("locator", "body"))
    quote = str(case.get("quote", title if locator == "title" else body_text))
    source_text = title if locator == "title" else body_text
    start_char = source_text.index(quote)
    end_char = start_char + len(quote)
    article_id = f"article-{name}"
    cluster_id = f"cluster-{name}"
    source_reference = SourceReference(
        source_id="graph-fixture",
        url=f"https://news.example.com/graph/{name}",
        provider_key=f"graph-{name}",
        original_locator=SourceReferenceLocator(
            locator_type="fixture",
            locator_value=name,
        ),
    )
    article = NewsArticleArtifact(
        article_id=article_id,
        source_id="graph-fixture",
        source_reference=source_reference,
        title=title,
        body_text=body_text,
        published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 3, 1, 0, 5, tzinfo=timezone.utc),
        language="en",
        author_or_channel="Graph Fixture",
        content_hash=f"sha256:{name}",
        article_fingerprint=f"sha256:{name}:fp",
        license_tag="fixture",
        reliability_tier=str(case.get("reliability_tier", "A")),
        cluster_id=cluster_id,
    )
    cluster = NewsDedupeCluster(
        cluster_id=cluster_id,
        representative_article_id=article_id,
        member_article_ids=[article_id],
        canonical_headline=title,
        first_published_at=article.published_at,
        source_count=int(case.get("source_count", 1)),
        fingerprint_family=f"sha256:{name}:family",
        cluster_confidence=0.92,
    )
    subject = _entity_from_case(case, prefix="subject")
    object_entity = _entity_from_case(case, prefix="object")
    evidence = EvidenceSpan(
        article_id=article_id,
        start_char=start_char,
        end_char=end_char,
        quote=quote,
        locator=locator,  # type: ignore[arg-type]
    )
    entity_resolution = EntityResolutionResult(
        mentions=[
            _mention_for_entity(article, source_reference, subject, locator=locator),
            _mention_for_entity(article, source_reference, object_entity, locator=locator),
        ],
        resolved_mentions=[
            _resolved_mention(article, source_reference, subject, locator=locator),
            _resolved_mention(article, source_reference, object_entity, locator=locator),
        ],
        entities=[subject, object_entity],
    )
    fact = NewsFactCandidate(
        candidate_id=f"fact-{name}",
        article_id=article_id,
        cluster_id=cluster_id,
        source_reference=source_reference,
        fact_type=str(case.get("fact_type", "contract")),
        summary=body_text,
        involved_entities=[subject, object_entity],
        event_time=None,
        evidence_spans=[evidence],
        confidence=0.9,
        source_reliability_tier=article.reliability_tier,
    )
    response = _runtime_response(case, subject, object_entity, evidence)
    return article, cluster, entity_resolution, [fact], response


def _entity_from_case(case: Mapping[str, object], *, prefix: str) -> InvolvedEntity:
    status = str(case.get(f"{prefix}_status", "resolved"))
    canonical_id = case.get(f"{prefix}_canonical_id")
    if canonical_id is None and status == "resolved":
        canonical_id = f"entity:{_safe_name(str(case[f'{prefix}_text']))}"
    return InvolvedEntity(
        mention_text=str(case[f"{prefix}_text"]),
        canonical_id=str(canonical_id) if canonical_id is not None else None,
        resolution_status=status,  # type: ignore[arg-type]
        type_hint=str(case.get(f"{prefix}_type_hint", "company")),
    )


def _runtime_response(
    case: Mapping[str, object],
    subject: InvolvedEntity,
    object_entity: InvolvedEntity,
    evidence: EvidenceSpan,
) -> Mapping[str, object]:
    if case.get("include_graph_delta", True) is False:
        return {"graph_deltas": []}
    return {
        "graph_deltas": [
            {
                "subject_entity": subject.model_dump(mode="json"),
                "relation_type": case["relation_type"],
                "object_entity": object_entity.model_dump(mode="json"),
                "delta_action": case.get("delta_action", "add"),
                "valid_from": None,
                "evidence_spans": [evidence.model_dump(mode="json")],
                "confidence": case.get("confidence", 0.9),
                "requires_manual_review": False,
            }
        ]
    }


def _mention_for_entity(
    article: NewsArticleArtifact,
    source_reference: SourceReference,
    entity: InvolvedEntity,
    *,
    locator: str,
) -> Mention:
    source_text = article.title if locator == "title" else article.body_text
    start_char = source_text.find(entity.mention_text)
    if start_char < 0:
        start_char = 0
    end_char = start_char + len(entity.mention_text)
    return Mention(
        article_id=article.article_id,
        text=entity.mention_text,
        start_char=start_char,
        end_char=end_char,
        locator=locator,  # type: ignore[arg-type]
        type_hint=entity.type_hint,
        context=source_text,
        source_reference=source_reference,
    )


def _resolved_mention(
    article: NewsArticleArtifact,
    source_reference: SourceReference,
    entity: InvolvedEntity,
    *,
    locator: str,
) -> ResolvedMention:
    return ResolvedMention(
        mention=_mention_for_entity(
            article,
            source_reference,
            entity,
            locator=locator,
        ),
        entity=entity,
        resolution_source="quick_path" if entity.resolution_status == "resolved" else "fallback",
        registry_resolution=None,
    )


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
