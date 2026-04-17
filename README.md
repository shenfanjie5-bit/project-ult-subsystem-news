# subsystem-news

This module is scaffold-only.

Source of truth:

- `docs/subsystem-news.project-doc.md`

Current workspace state:

- `docs/` keeps the source project doc
- `pyproject.toml` is placeholder project metadata
- implementation directories are created only when real work starts

Execution rule:

1. read the project doc first
2. keep work inside this module unless the issue explicitly targets shared contracts
3. do not treat this scaffold as finished implementation

## 模块导航

| Module | Responsibility |
|--------|----------------|
| `subsystem_news.sources` | Discovers and fetches approved news articles while enforcing source access policy. |
| `subsystem_news.normalize` | Normalizes article title, body, publication time, and source metadata. |
| `subsystem_news.dedupe` | Computes article fingerprints and manages repost deduplication clusters. |
| `subsystem_news.entities` | Coordinates mention extraction with entity-registry resolution. |
| `subsystem_news.extract` | Produces fact extraction and event classification outputs for Ex-1 candidates. |
| `subsystem_news.signals` | Builds Ex-2 signal candidates and checks required signal constraints. |
| `subsystem_news.graph` | Produces Ex-3 graph delta candidates only for high-confidence relation evidence. |
| `subsystem_news.runtime` | Assembles pipeline flow, submit integration, and replay entry points. |
| `subsystem_news.fixtures` | Holds fixtures, labeled samples, and regression assets for later stages. |
