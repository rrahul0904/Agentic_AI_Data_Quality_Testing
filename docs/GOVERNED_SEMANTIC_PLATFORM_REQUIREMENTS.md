# Governed Semantic Platform — Product Requirements

## Product objective

Build an enterprise semantic platform centered on Snowflake that defines business entities, dimensions, relationships, metrics, and verified analytical questions once and exposes the same governed definitions to:

- Snowflake SQL and analytics;
- Microsoft Power BI;
- Microsoft Excel;
- AI clients through Cortex Agent / MCP.

The product is not an RGA data generator. The RGA-style Life & Health reinsurance dataset is the synthetic reference workload used to prove correctness, scale, change handling, and cross-consumer parity without production or proprietary data.

This project is intentionally not named or implemented as Catalyst.

## Core problem

Enterprises frequently reproduce business logic across SQL, dbt, Power BI DAX, Excel formulas, dashboards, and AI prompts. That creates semantic drift: two users can ask for the same measure and receive different answers.

The platform must establish one governed semantic source of truth and make downstream clients consume or validate against that source instead of redefining the measures.

## Required architecture

1. Physical data layer in Snowflake
   - RAW ingestion
   - STAGING normalization
   - CORE facts/dimensions
   - MART models optimized for analytical access

2. Canonical semantic contract
   - entities and grain
   - dimensions and time dimensions
   - facts
   - metrics
   - relationships
   - synonyms/descriptions
   - verified analytical questions
   - consumer policies
   - performance acceptance targets

3. Snowflake Semantic View
   - compiled from the canonical contract
   - server-side verified before deployment
   - create/alter deployment kept separate from verification

4. Consumer surfaces
   - Snowflake SQL using the governed Semantic View
   - Cortex Agent using the same Semantic View
   - managed MCP exposing the governed Agent rather than unrestricted SQL
   - Power BI and Excel using the governed Microsoft semantic path when the target account exposes the required endpoint/capability
   - automated Power BI parity capture through Execute DAX Queries when an actual supported Power BI semantic model is available
   - Excel remains a separate governed live/XMLA evidence surface; Power BI API evidence never substitutes for Excel evidence
   - no client-side recreation of governed derived measures for parity certification

5. Performance and scale layer
   - benchmark direct MART SQL versus Semantic View queries for identical business questions
   - concurrency checkpoints at 1, 5, 10, 25, and 50
   - capture query IDs, latency, queueing, bytes scanned, partitions, cache behavior, and spill
   - use Snowflake physical optimization independently from semantic definition: warehouse sizing/concurrency, clustering, materialization/dynamic tables, search optimization, and other justified acceleration mechanisms
   - never change the business definition merely to make one consumer faster

6. Change-data behavior
   - policy updates
   - premium corrections
   - late-arriving claims
   - replay/idempotency scenarios
   - incremental model and semantic-result correctness after changes

## Single-source-of-truth rule

config/rga_semantic_contract.yml is the reference implementation of the canonical contract for the RGA test workload.

The following artifacts must compile from that contract:

- Snowflake Semantic View;
- Cortex Agent resource binding;
- Microsoft Power BI/Excel parity contract;
- direct-versus-semantic benchmark queries;
- governed metric inventory;
- performance acceptance metadata.

A metric change is incomplete if it requires independent edits in multiple consumer-specific files.

## Cross-consumer parity acceptance

For every canonical verified query:

Snowflake Semantic View result = AI governed result = Power BI governed result = Excel governed result

at the same:

- dimensional grain;
- filter context;
- time grain;
- role/security context;
- metric definition.

Connectivity alone is not parity. A Power BI Execute DAX Queries result can certify the Power BI semantic-model surface only when it comes from the governed model under the intended security context; it does not certify Excel. Excel must produce its own governed live/XMLA evidence.

A Power BI report or Excel workbook that connects to Snowflake but recreates CEDED_LOSS_RATIO, CEDED_PREMIUM_RATE, or any other governed metric locally does not pass semantic certification.

## RGA synthetic workload role

The RGA-style dataset is used to create realistic:

- cedants;
- treaties;
- policies and coverages;
- underwriting outcomes;
- premiums;
- claims/payments/reserves;
- exposure;
- corrections and late arrivals.

It must support bounded developer runs and large target profiles so the semantic platform can be tested against realistic relationship complexity and high data volume.

No proprietary RGA dataset or real-person PII is required or permitted for this reference workload.

## Production-readiness evidence

Repository certification must prove deterministic generation and compilation without external credentials.

Live certification must separately prove:

- Snowflake object creation;
- RAW load;
- dbt build/tests;
- Semantic View server verification/deployment;
- direct versus semantic benchmark evidence;
- Cortex Agent/MCP runtime evidence;
- Power BI governed semantic parity through live/XMLA and/or Execute DAX Queries evidence when the target Power BI semantic model supports it;
- Excel governed semantic parity through its own live/XMLA client evidence;
- target-account capability/entitlement detection for the Snowflake Semantic Views XMLA endpoint rather than assuming repository configuration proves availability.

Repository-green is not the same as live-environment-certified.

## Success criteria

The implementation is successful when an enterprise can define a business metric once, deploy it as a governed Snowflake semantic object, query it from SQL/Power BI/Excel/AI, receive the same result across those surfaces, and sustain acceptable performance at enterprise data volume and concurrency without copying the metric logic into each client.
