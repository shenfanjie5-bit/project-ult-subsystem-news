# Full Mode Interface Stability

This note records the Full-mode interface rules for milestone 5, following
project document sections 11.9, 16.3, and 21. The goal is to keep the future
`stream-layer` consumer on stable structured `Ex-2` JSON. Consumers must not
reinterpret original article text, and backend or provider changes must not
change news-domain schemas.

## Frozen Ex-2 Stream Fields

`NewsSignalCandidate` is the stream-facing `Ex-2` contract. These fields are
frozen for Full-mode consumers:

- `candidate_id`
- `article_id`
- `cluster_id`
- `source_reference`
- `signal_type`
- `direction`
- `magnitude`
- `affected_entities`
- `impact_scope`
- `time_horizon`
- `rationale`
- `confidence`
- `evidence_spans`
- `export_contract`

The required stream fields are:

- `signal_type`
- `direction`
- `magnitude`
- `affected_entities`
- `impact_scope`
- `time_horizon`
- `source_reference`
- `evidence_spans`
- `export_contract`

`source_reference` keeps every signal traceable to the originating article.
`evidence_spans` must be present and non-empty. `affected_entities` must be
present and non-empty. Missing or empty evidence remains a local contract error
before submit.

Any change to these field names, enum literals, or `export_contract` values is a
contract upgrade and must be handled in a separate schema migration issue.

## Schema Pins

Structured generation calls pin schema identity and output version at the domain
boundary:

- `Ex-1`: `news_fact_candidate`, `news_fact_candidate.v1`,
  `news_fact_candidate.output.v1`
- `Ex-2`: `news_signal_candidate`, `news_signal_candidate.v1`,
  `news_signal_candidate.output.v1`
- `Ex-3`: `news_graph_delta_candidate`, `news_graph_delta_candidate.v1`,
  `news_graph_delta_candidate.output.v1`

Replay metadata must preserve `schema_pins` with these values. Regression checks
must compute `Ex-2` completeness from replayed `candidate_payloads`, not from
expected declarations or snapshot self-comparison.

## Backend Switch Rules

The news runtime selects a reasoner client through
`RuntimeBackendConfig` and `resolve_reasoner_client()`.

Allowed environment keys:

- `SUBSYSTEM_NEWS_REASONER_BACKEND`
- `SUBSYSTEM_NEWS_REASONER_CONFIG_VERSION`
- `SUBSYSTEM_NEWS_REASONER_PROVIDER`
- `SUBSYSTEM_NEWS_REASONER_MODEL`
- `SUBSYSTEM_NEWS_REASONER_FALLBACK_BACKEND`

Default behavior resolves `backend_name == "reasoner-runtime"` to
`DefaultReasonerRuntimeClient`. Deployments and tests may provide a registry of
backend factories keyed by backend name. These factories must return objects that
implement `ReasonerRuntimeClient.generate_structured(request)`.

Client selection order in `run_once()` is:

1. Explicit `reasoner_client`
2. Dry-run noop client
3. `resolve_reasoner_client(load_runtime_backend_config())`

Switching backend, provider, model, or fallback backend must not require changes
under `extract/`, `signals/`, or `graph/`. Those modules continue to consume and
produce provider-neutral `StructuredGenerationRequest` and candidate contracts.

## Prohibited Changes

This milestone does not introduce:

- Kafka
- Flink
- CEP
- Temporal
- Neo4j direct writes
- Provider SDK imports
- Provider API key reads in news-domain code
- Stream topic management
- A stream-layer consumer

Backend/provider/fallback behavior belongs in the `reasoner-runtime`
configuration layer. The news subsystem only validates stable candidate payloads
and submits locally checked contracts.
