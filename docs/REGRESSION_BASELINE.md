# Regression Baseline

This baseline freezes the milestone-4 replay fixture suite for CI-friendly
replay, diff, and metric checks. It does not expand source discovery and does
not reimplement runtime pipeline logic inside `fixtures/`.

## Suite

- Suite ID: `milestone4-regression`
- Suite version: `2026-04-18.v1`
- Manifest: `src/subsystem_news/fixtures/regression/manifest.json`
- Baseline snapshots: `src/subsystem_news/fixtures/regression/baseline/*.json`

## Fixture Scale

| Category | Cases | Articles | Purpose |
| --- | ---: | ---: | --- |
| `single_source` | 1 | 1 | Standard normalized article with multiple fact/signal outputs |
| `repost_cluster` | 10 | 20 | Curated duplicate repost clusters folded to one Ex-2 per event |
| `ambiguous_entity` | 1 | 1 | Ambiguous/unresolved mentions remain explicit |
| `graph_positive` | 1 | 1 | Strong Ex-3 relation with manual review requirement |
| `ex1_only` | 1 | 1 | Unresolved-only Ex-1 boundary with no Ex-2 promotion |
| `graph_negative` | 30 | 30 | Reviewed negative set covering cooccurrence, sentiment-only, title association, summary-only, and unresolved/ambiguous entities |

## Baseline Metrics

| Metric | Baseline | Threshold |
| --- | ---: | ---: |
| Evidence coverage | `1.0000` | `>= 1.0000` |
| Dedupe precision | `1.0000` | `>= 0.9500` |
| Unresolved explicitness | `1.0000` | `>= 1.0000` |
| Ex-2 contract completeness | `1.0000` | `>= 1.0000` |
| Ex-3 false-positive rate | `0.0000` | `<= 0.0100` |

## Version Pins

Every fixture case declares the current schema pins:

- `Ex-1`: `news_fact_candidate.v1`, output `news_fact_candidate.output.v1`
- `Ex-2`: `news_signal_candidate.v1`, output `news_signal_candidate.output.v1`
- `Ex-3`: `news_graph_delta_candidate.v1`, output `news_graph_delta_candidate.output.v1`

Each baseline snapshot also stores `metadata.schema_pins` and
`metadata.replay_version = fixture-baseline.v1` so replay diffs can surface
schema pin drift separately from candidate and evidence drift. The same
snapshots include `metadata.metrics_summary` with the checked-in baseline
metric values.
