# External Research: Governed Snowflake Semantic Platform

Research date: 2026-09-18

## Requirement being researched

The target is not merely a semantic YAML model. It is an enterprise platform with:

- one governed business definition;
- Snowflake-native execution;
- Power BI and Excel consumption without rebuilding metric logic;
- AI/Cortex/agent consumption of the same semantics;
- Git/CI/CD lifecycle and validation;
- enterprise performance using materialization/pre-aggregation and concurrency controls;
- synthetic RGA-style data for repeatable large-scale validation;
- cross-consumer parity evidence.

No single open-source repository currently covers the whole requirement. The best implementation path is to compose proven patterns from several projects and retain Snowflake Semantic Views as the governed runtime object.

## Highest-value GitHub donors

### Snowflake-Labs/dbt_semantic_view

URL: https://github.com/Snowflake-Labs/dbt_semantic_view

Use for:
- Snowflake Semantic View dbt materialization;
- CREATE OR ALTER lifecycle;
- MAX_STALENESS;
- declarative semantic-view materializations;
- integration-test patterns;
- preserving materializations instead of dropping them on every release.

Adopt:
- declarative materialization management;
- dbt integration tests against Snowflake;
- create-or-alter release discipline.

Do not duplicate:
- the full package. Our platform should either consume it or implement a very thin compatible boundary.

### WhoopInc/snowflake-semantic-tools

URL: https://github.com/WhoopInc/snowflake-semantic-tools

Use for:
- semantic-as-code CLI lifecycle;
- offline compilation;
- validation rules;
- enrichment;
- diff-before-deploy;
- only-modified/incremental deployments;
- local manifest design.

Adopt:
- validation/diff/release evidence patterns;
- semantic manifest as a build artifact;
- dependency/change impact detection.

### apache/ossie

URL: https://github.com/apache/ossie

Use for:
- vendor-neutral semantic interchange;
- portability across dbt, Snowflake, Salesforce/Tableau, Databricks and other semantic ecosystems;
- schema validation;
- converter architecture.

Adopt:
- import/export adapter boundary;
- canonical portable representation where it does not weaken Snowflake-native capabilities.

Constraint:
- Snowflake Semantic Views can contain capabilities beyond the common interchange standard, so Ossie should be an interoperability boundary, not the only internal model.

### sidequery/sidemantic

URL: https://github.com/sidequery/sidemantic

Use for:
- translating/importing multiple semantic formats;
- Power BI TMDL/DAX interoperability;
- MetricFlow, LookML, Cube, Cortex, Ossie and AtScale format handling;
- SQL/CLI/Python/HTTP/BI/AI consumption surfaces.

Adopt:
- adapter architecture;
- round-trip and translation tests;
- import conflict reporting.

### dbt-labs/metricflow

URL: https://github.com/dbt-labs/metricflow

Use for:
- semantic query compiler architecture;
- multi-hop joins;
- derived/ratio/cumulative metrics;
- time-grain handling;
- query planning and SQL rendering.

Adopt:
- query-plan concepts and semantic-expression validation;
- complex metric semantics tests.

Do not replace Snowflake Semantic Views with MetricFlow for the target architecture; use it as a compiler/design donor and potential import source.

### cube-js/cube

URL: https://github.com/cube-js/cube

Use for:
- high-concurrency semantic serving;
- pre-aggregation matching;
- cache/pre-aggregation lifecycle;
- semantic APIs for BI and AI.

Adopt:
- workload fingerprinting;
- pre-aggregation recommendation/matching ideas;
- refresh orchestration and high-concurrency thinking.

Do not introduce Cube as a second production semantic truth unless there is a deliberate architecture decision. Snowflake remains the governed runtime for this project.

### Snowflake-Labs/sfguide-getting-started-with-cortex-agents

URL: https://github.com/Snowflake-Labs/sfguide-getting-started-with-cortex-agents

Use for:
- Cortex Analyst + Cortex Search + Cortex Agent integration;
- REST/API test patterns;
- agent deployment/smoke-test flow.

Adopt:
- live Agent API certification and response-evidence capture.

### Snowflake-Labs/semantic-model-generator

URL: https://github.com/Snowflake-Labs/semantic-model-generator

Status:
- superseded by native Semantic View generation in Snowsight.

Use only as historical donor for:
- metadata introspection;
- semantic-model bootstrapping;
- generated-description workflows.

Do not build new product dependencies around it.

## Snowflake-native capabilities that materially change the design

### Semantic View materializations

Snowflake now supports materializing selected Semantic View dimensions/metrics and automatically rewriting eligible Semantic SQL queries to lower-cost materializations.

Important behavior:
- MAX_STALENESS is required;
- multiple materializations can coexist;
- Snowflake chooses the lowest-cost covering materialization;
- additive metrics can be reaggregated;
- CREATE OR ALTER preserves compatible materializations;
- CREATE OR REPLACE drops them;
- Cortex Analyst / Cortex Agent physical SQL does not automatically benefit from Semantic View materializations when those tools execute underlying physical SQL directly.

Implementation consequence:
the acceleration engine needs two paths:
1. Semantic SQL materialization recommendations;
2. underlying MART/Dynamic Table/physical optimization for AI-generated physical SQL.

### Power BI and Excel

Snowflake Semantic Views XMLA Endpoint powered by AtScale is the closest implementation of the exact Microsoft requirement:
- live Power BI via DAX/XMLA;
- live Excel via MDX/XMLA;
- one Snowflake semantic definition;
- Snowflake RBAC passthrough;
- no mirrored semantic model required.

Current availability must remain feature-gated in our implementation.

Power BI Semantic View Autopilot ingestion is also relevant in the reverse direction:
Power BI PBIX/PBIT -> Snowflake Semantic View.

This should become an import/migration path, not a second source of truth.

## Reddit implementation lessons

### Semantic layer must work in Excel / pivot-table workflows

Repeated practitioner feedback is that a semantic layer that does not reach spreadsheet/pivot users will be bypassed. This directly validates keeping Excel as a first-class acceptance surface rather than an optional future integration.

### Power BI DirectQuery can fan out aggressively

Practitioners report that a visually simple Power BI page can generate many SQL queries, and Snowflake itself may be fast while the end-to-end dashboard still feels slow.

Implementation consequence:
- benchmark end-to-end query fan-out, not just single-query Snowflake latency;
- record concurrency, queueing and number of SQL statements per user action;
- evaluate aggregation/materialization strategies with realistic dashboard workloads.

### Semantic View production concerns are lifecycle concerns

Practitioners repeatedly ask about:
- versioning;
- review;
- dbt generation;
- CI/CD;
- drift;
- production ownership.

This validates the semantic compiler, canonical contract, diff-before-deploy and exact-head certification work already added to PR #17.

### Multi-fact models remain a stress case

Community reports show shared-dimension / multiple-fact questions can expose modeling limitations or force awkward structures.

Implementation consequence:
RGA test coverage should expand from one performance mart into at least:
- premium fact;
- claim fact;
- exposure fact;
- shared cedant/treaty/date dimensions;
- a combined business question that requires safe multi-fact semantics without fan-out.

## Medium/article implementation lessons

### Snowflake + Power BI architecture requires explicit trade-offs

Snowflake engineering articles distinguish:
- Power BI Import;
- DirectQuery;
- external/native semantic layers;
- aggregation tables;
- Snowflake-side modeling.

Implementation consequence:
our certification needs both semantic correctness and user-perceived performance; a connection that is logically correct but produces unusable dashboard latency is a failed architecture.

### Metrics-as-code is a mature pattern

dbt/MetricFlow examples reinforce:
- model business semantics above curated marts, not raw/staging;
- version metrics in Git;
- test joins/grains;
- avoid metric logic hidden inside BI clients.

Our canonical semantic contract already follows this direction.

### AI accuracy depends on semantic quality, not only the LLM

Snowflake/Cortex write-ups consistently emphasize:
- descriptions;
- synonyms;
- relationship accuracy;
- verified queries;
- scope/rejection rules.

Implementation consequence:
semantic regression tests should include natural-language questions, expected metric references, expected grain, and rejected/ambiguous questions.

## Recommended donor plan for this project

| Capability | Primary donor | Action |
| --- | --- | --- |
| Semantic View dbt lifecycle | Snowflake-Labs/dbt_semantic_view | integrate/adapt |
| Validation/diff/manifest | WhoopInc/snowflake-semantic-tools | reverse engineer |
| Interchange standard | apache/ossie | add adapter |
| Multi-format import/export | sidequery/sidemantic | reverse engineer |
| Complex metric compiler | dbt-labs/metricflow | borrow semantics/tests |
| Acceleration/pre-aggregation | cube-js/cube + Snowflake SV materializations | reverse engineer |
| AI runtime | Snowflake Cortex Agents | implement/live certify |
| AI external protocol | Snowflake managed MCP | implement/live certify |
| Power BI/Excel live semantics | Snowflake/AtScale XMLA | feature-gated integration |
| Power BI migration/import | Snowflake Semantic View Autopilot | add import workflow |
| Scale workload | RGA synthetic pack | continue building |

## Immediate engineering consequences

1. Add semantic-view materialization planning and generated materialization YAML/DDL.
2. Separate acceleration recommendations for Semantic SQL from physical SQL used by Cortex.
3. Add workload/query-history fingerprinting that groups repeated semantic questions.
4. Add multi-fact semantic test cases for premium + claim + exposure.
5. Add adapter interfaces for Ossie and Power BI model ingestion.
6. Add end-to-end BI workload evidence format that captures query fan-out in addition to p95 latency.
7. Add semantic regression cases for answerable, ambiguous and rejected AI questions.
8. Keep Power BI/Excel XMLA live certification feature-gated until enabled in the target Snowflake account.


## Confidence-gated implementation status

Only donor patterns with implementation confidence >=75% are being absorbed automatically.

| Donor/resource | Confidence | Implemented in PR #17 |
| --- | ---: | --- |
| Snowflake-Labs/dbt_semantic_view declarative materializations + CREATE OR ALTER discipline | 95% | Yes: MAX_STALENESS policy, materialization candidates, declarative YAML, SYSTEM$MANAGE_SEMANTIC_VIEW_MATERIALIZATIONS_FROM_YAML sync template |
| WhoopInc/snowflake-semantic-tools compiled manifest / checksums / diff-before-deploy | 92% | Yes: canonical semantic manifest, stable component hashes, change diff, impacted-artifact graph, release bundle |
| Apache Ossie semantic interchange | 88% | Yes, export-only: governed core exported to Ossie; Snowflake-only behavior preserved as custom extensions; explicit compatibility/loss report |
| Cube pre-aggregation / workload-shape matching pattern | 85% | Yes: canonical metric+dimension fingerprints, repeated-workload telemetry analysis, evidence-backed acceleration recommendations |
| MetricFlow query-planning / safe multi-fact aggregation pattern | 90% | Yes: premium/claim/exposure are independently aggregated to shared grain before joining; multi-fact certification plan and reference SQL |
| Sidemantic adapter registry / explicit format capability pattern | 82% | Partially: export direction and compatibility/loss boundary implemented for Ossie; broad automatic import remains intentionally disabled pending lossless mapping |
| Snowflake Power BI Autopilot ingestion | 90% for migration use case | Researched and documented; no binary PBIX/PBIT parser duplicated because Snowflake already owns the ingestion path |
| AtScale/Snowflake XMLA live Power BI + Excel | 90% architecture fit | Existing feature-gated Microsoft contract/parity suite; live endpoint evidence remains external |
| Cortex Agent + governed Semantic View | 95% | Existing Agent/MCP generation and parity requirements; live runtime evidence remains external |

Lower-confidence or unnecessarily duplicative implementations are not being copied merely because a repository exists. The goal is to absorb proven architectural mechanisms while keeping Snowflake Semantic Views as the governed runtime and avoiding a second semantic truth.
