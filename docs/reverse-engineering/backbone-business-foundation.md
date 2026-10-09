# Backbone by Calon → Business Foundation Compiler

Status: **RESEARCHED → SPECIFIED; implementation not started**  
Snapshot: 2026-10-09  
Coordination issue: `rrahul0904/agent-work-os#85`

## Source set

Primary user-supplied source:

- https://lnkd.in/p/gevGWUW5
- resolved LinkedIn post: https://www.linkedin.com/posts/nathanjonesdata_snowflake-context-share-7514200254972448768-3jCY/

First-party public evidence:

- https://www.calonanalytics.com/
- https://www.calonanalytics.com/manifesto
- https://www.linkedin.com/pulse/backbone-manifesto-nathan-jones-lu7pe
- https://www.linkedin.com/posts/nathanjonesdata_datavault-dbt-snowflake-activity-7287836567946055680-MK-6
- https://www.linkedin.com/posts/nathanjonesdata_snowflake-dbt-cortex-activity-7485693528447160320-_iSB

Comparator/platform evidence:

- Snowflake Semantic Views documentation
- dbt Semantic Layer / MetricFlow / MCP documentation
- WhereScape Data Vault automation product material

This dossier uses public behavior and product claims only. It does not inspect any private Backbone service, private API, binary, prompt, model, schema, internal repository, or customer environment.

## Current public claim

The supplied post reports a client order-to-cash implementation produced in about three weeks with **542 dbt models** and **799 dbt tests**, spanning two stores and Snowflake. The post says the system begins with a natural-language brief; performs data investigation; generates tests and documentation; creates semantic models and MCP integration; retains rule/preference/context artifacts; and uses AI to generate configuration while deterministic machinery generates or executes the material parts of the pipeline.

The post also states that Backbone projects of this size start around €20k, versus an author-estimated €200–300k conventional consulting engagement. Treat the economics, delivery-speed, and scale figures as first-party claims rather than independent benchmarks.

## Reconstructed Backbone workflow

An earlier first-party Backbone trial description provides the strongest public workflow evidence:

1. Read source metadata already landed in Snowflake.
2. Use AI to propose integration instructions and map source structures toward a common ontology/model where appropriate.
3. Detect likely PII, amounts, dates, identifiers and keys.
4. Review and correct the generated integration instructions, including hard business rules and cross-system business-key alignment.
5. Generate Data Vault-oriented dbt structures, initially raw vault and point-in-time layers plus a first test set.
6. Iterate on the integration configuration until accepted.
7. Add business-vault logic such as unit economics, customer/SKU profiles and bridges.
8. Define metrics, charts and dashboards.
9. Run the complete pipeline and validate results against expected business outcomes.

Newer Backbone material reframes the input contract as **business entities + jobs to be done + sources**, then generates the warehouse, semantic layer and MCP context from a business ontology. Public positioning also says the customer retains data in Snowflake and artifacts/code in Git.

## What is actually differentiated

The reusable idea is not simply dbt generation, semantic metrics or MCP. ADE OS already has substantial implementations of those.

The stronger donor concept is an **upstream business-foundation compiler** that starts from business intent rather than only from physical schema:

```text
business brief / JTBD
        ↓
business ontology
        ↓
source catalog + profiling
        ↓
AI mapping proposals (advisory only)
        ↓
human-reviewed approved foundation config
        ↓
deterministic generation plan
        ↓
dbt / Snowflake / semantic / DQ / MCP artifacts
        ↓
reconciliation + verification evidence
```

The most important design separation is:

1. **Discovery** — what physically exists in the sources?
2. **Meaning** — what entities, metrics, grains, decisions and source-of-truth rules does the business actually intend?
3. **Proposal** — what mappings/rules does AI suggest?
4. **Authority** — what exact configuration has been reviewed and approved?
5. **Generation** — what deterministic artifacts should the approved configuration produce?
6. **Proof** — do the generated artifacts reconcile to expected business facts?

## Public-feedback requirements

The supplied LinkedIn discussion contains substantive criticism that should directly shape the design:

- A graph containing 542 models does not prove that 542 models are necessary.
- A count of 799 tests says little about test value; null checks and business reconciliations are not equivalent.
- Deterministic execution can still execute the wrong business logic deterministically.
- Configuration that defines joins, transformations, dependencies or rules is code in all material respects and requires code-level governance.
- Delivery-cost comparisons are only meaningful if deliverables, correctness, maintainability and acceptance criteria are actually comparable.

Therefore ADE must not treat generated model/test counts as success metrics.

## Internal donor audit

Canonical destination: **Agentic Data Engineering OS** in this repository.

Do not create another semantic-layer or Snowflake automation repository. Do not route this work into `snowflake-brain`, any Snowflake certification/question-bank artifact, or Catalyst.

Existing ADE foundations to reuse:

- repository/source discovery;
- dbt parsing, lineage, testing and generation;
- Snowflake connectors and live-testbed support;
- semantic contract compiler and Snowflake Semantic View generation;
- Cortex Agent/MCP artifacts;
- synthetic enterprise-domain generation;
- Data Quality, Data Diff and reconciliation;
- cross-system lineage and impact analysis;
- Power BI / Excel parity contracts;
- governed control plane and exact-SHA evidence gates.

Merged PR #25 already delivered the governed semantic-platform repository integration. The missing donor value is mainly **business-first foundation compilation before the semantic layer**, not another semantic runtime.

## Product thesis

Add a provider-neutral **Business Foundation Compiler** to ADE OS.

The compiler must treat AI as a proposal engine, never as authority. Only an immutable reviewed configuration can drive deterministic generation.

### Core contracts

#### `BusinessOntology`

Required fields:

- version
- entities
- entity grain
- relationships and cardinality
- dimensions
- metrics and metric definitions
- synonyms / business vocabulary
- jobs-to-be-done and decisions supported
- business keys
- source authority / conflict-resolution policy
- owner / steward
- canonical digest

#### `SourceCatalog`

Required fields:

- source-system identity
- tables / objects / columns
- types
- key candidates
- amount/date/PII candidates
- profiles/statistics where available
- provenance
- observation timestamp / freshness
- canonical digest

Unknown must remain unknown. The contract must never convert missing metadata into confidence.

#### `MappingProposal`

AI/advisory artifact containing:

- source field or object
- candidate business concept
- rationale
- evidence anchors
- confidence
- candidate transform
- candidate business-key relationship
- explicit unresolved/ambiguous state

A proposal has **no execution authority**.

#### `ApprovedFoundationConfig`

Reviewed configuration containing:

- exact ontology digest
- exact source-catalog digest
- accepted mappings
- accepted transforms
- accepted business-key relationships
- accepted metric/grain rules
- reviewer/approval record
- approval timestamp
- immutable config digest

Any material edit invalidates approval.

#### `GenerationPlan`

Side-effect-free deterministic plan containing:

- exact approved-config digest
- explicit architecture policy
- planned warehouse/dbt/semantic/DQ artifacts
- model class and purpose
- dependency graph
- test portfolio by risk class
- reconciliation requirements
- complexity/model-count receipt
- generated plan digest

Phase A must be dry-run only.

## Architecture policy

Data Vault is one allowed architecture lane, not a mandatory outcome.

The architecture decision should be explicit and testable, for example:

- normalized staging/core/marts;
- Data Vault raw/business/PIT/bridge;
- star schema / dimensional marts;
- hybrid composition.

The generator must justify why a layer/model exists. Architecture policy is part of the approved configuration and contributes to the deterministic digest.

## Complexity policy

Generated-model throughput is not a KPI.

The plan should emit a complexity receipt with at least:

- number of source objects;
- number of generated models by class;
- number of relationship edges;
- fan-in/fan-out outliers;
- duplicated transformations detected;
- purpose/rationale for every generated model class;
- configured complexity budget;
- explicit approval when the budget is exceeded.

A system that generates 542 models where 120 would be sufficient should fail a maintainability review even if all 542 compile.

## Test-quality policy

A raw test count is insufficient. The generated test portfolio should classify coverage into at least:

1. schema/contract tests;
2. key/relationship integrity tests;
3. freshness/volume/change tests;
4. transformation/business-rule tests;
5. source-to-target reconciliation tests;
6. semantic/metric correctness tests;
7. regression/change-impact tests.

High counts of low-value assertions must not satisfy business-risk coverage gates.

For order-to-cash style use cases, the verifier should be able to express and measure facts such as:

- order counts by source and state;
- line-item amount reconciliation;
- tax/discount/shipping/net/gross reconciliation;
- duplicate/missing business keys;
- unmatched entities across source systems;
- late-arriving corrections;
- source-authority conflicts;
- metric parity across warehouse, semantic layer and downstream consumers.

## Change and acquisition flow

Backbone's acquisition story is useful but must be evidence-backed.

A new source/brand/ERP should follow:

```text
new source discovery
→ ontology overlap analysis
→ new/changed mapping proposals
→ conflict detection
→ impact graph
→ review/approval
→ deterministic regeneration plan
→ bounded artifact diff
→ reconciliation
→ release evidence
```

No existing metric or mapping may silently change because a new source is added.

## Phase A acceptance contract

Before implementation is allowed to advance, tests must prove:

- identical approved config produces identical generation-plan digest;
- object-key ordering does not alter canonical digests;
- edited ontology invalidates previous approval;
- edited mappings invalidate previous approval;
- MappingProposal cannot execute directly;
- missing business grain blocks affected metrics;
- missing source authority blocks unresolved conflicting metrics;
- two conflicting revenue definitions cannot silently collapse into one metric;
- ambiguous cross-system business key remains unresolved rather than guessed;
- stale source metadata becomes review/unknown per explicit freshness policy;
- a high test count without reconciliation coverage fails the quality gate;
- complexity budget overrun requires rationale/approval;
- deterministic generation cannot self-certify business correctness;
- a new source produces impact analysis before artifact mutation.

## Implementation phasing

### Phase A — contracts + deterministic dry-run planner

Implement the five core contracts and deterministic planning/digest logic. No Snowflake/dbt mutation.

### Phase B — synthetic multi-source order-to-cash proving ground

Use ADE synthetic generation to create two deliberately inconsistent commerce/order systems and one finance reference. Prove mapping approval, cross-system business-key handling, late-arriving data, conflicting revenue definitions and reconciliation.

### Phase C — dbt/Snowflake artifact generation

Bind the approved plan into existing ADE dbt/Snowflake generators. Preserve exact config/plan/artifact hashes and deterministic diffs.

### Phase D — semantic/MCP propagation

Generate or update Snowflake Semantic Views, governed metrics, Cortex/MCP context and existing consumer contracts from the exact approved business foundation.

### Phase E — downstream parity

Verify governed metrics against MCP/AI answers, Power BI and Excel where configured. Consumer parity is evidence, not an assumption.

### Phase F — live change/acquisition certification

On a permitted Snowflake target, certify source addition, impact preview, regeneration, reconciliation, rollback/recovery and exact-SHA release evidence.

## Current WIP / truthful status

This branch intentionally stops at **research/specification + Shipping Contract**.

ADE currently has active draft work for local-first deployment and RE-239. Starting another full feature implementation lane would violate the bounded-WIP roadmap. This dossier makes the next build slice executable without pretending that code/runtime evidence already exists.

## Clean-room / IP boundary

- Do not copy Backbone branding, assets, screenshots, copy, schemas or private internals.
- Do not access a private Backbone environment for reverse engineering.
- Use public behavioral evidence only.
- Independently author ADE contracts, fixtures, generators and UI.
- Public marketing numbers are not acceptance evidence.

## Explicit non-claims

- no Backbone parity;
- no private-internal reconstruction;
- no proof that 542 models were necessary;
- no proof that 799 tests were sufficient;
- no live Snowflake certification for this donor slice;
- no production deployment claim;
- no feature implementation on this research branch yet.
