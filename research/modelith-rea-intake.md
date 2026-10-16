# Modelith REA intake → ADE OS Logical Model Compiler

Snapshot: 2026-10-16

## Source identity

User-supplied source:
- LinkedIn: https://lnkd.in/p/gVTB8tts
- Resolved post: Oleg Agapov, "I found a data modeling tool built for dbt! It’s called Modelith"

Canonical public upstream:
- https://github.com/dbose/modelith
- inspected `main` SHA: `f1f49a5d4194abe762a8e48b56463e1d603ec286`
- inspected upstream release line: `modelith-dbt` CLI `0.7.0`
- license: Apache-2.0

## Roadmap / repository classification

Classification: **DONOR / MODULE OF EXISTING OWNED PRODUCT**.

Canonical implementation destination: `rrahul0904/Agentic_AI_Data_Quality_Testing` (ADE OS).

Governance / evidence / shipping truth remains in `rrahul0904/agent-work-os`.

Do **not** create a standalone Modelith clone or another data-modeling repository at intake. Modelith overlaps heavily with capabilities already owned by ADE OS and with adjacent owned work:

- Agent Work OS issue #85 — Backbone/Calon → business-first ontology compiler for ADE OS.
- Agent Work OS issue #70 — Warehouse Refactor Engine / safe transformation refactoring.
- Agent Work OS issue #89 — Data Workbench / agentic SQL workspace.
- Existing ADE OS semantic-contract / Snowflake Semantic View / dbt / data-quality / reconciliation work.

The missing capability is the **canonical Git-native logical model intermediate representation and its round-trip compiler/runtime**, not another standalone semantic layer.

## Why we have not already built this

We built the ingredients in separate lanes but did not converge them into one modeling product boundary:

1. ADE OS focused on data quality, semantic contracts, Snowflake/dbt generation, lineage and reconciliation.
2. Backbone work added business ontology / source mapping / deterministic generation upstream.
3. Warehouse Refactor work focused on safe transformation changes, replay windows and data/schema diffs.
4. Data Workbench focused on database/query/operator workflows.
5. Technical Visual Studio / diagram work focused on visualization rather than an authoritative data-model compiler.

What remained absent was the center of gravity Modelith demonstrates:

`business meaning / source metadata -> canonical logical model in Git -> visual + IDE editing -> deterministic multi-target generation -> reverse engineering -> drift/diff -> governed reconciliation`

Without that canonical model IR, our downstream generators and upstream ontology work can coexist but do not share one authoritative round-trip artifact.

## Public behavior reconstructed

Modelith currently demonstrates these capability families:

### Authoring
- entities, attributes, domains and reusable reference data;
- primary/alternate/unique/index key groups;
- relationships and cardinality;
- subtypes/supertypes;
- subject areas / scoped model views;
- user-defined properties;
- visual ER canvas;
- VS Code / language-server workflow;
- plain YAML stored in Git as the source of truth.

### Forward compilation
- runnable dbt models;
- model contracts and dbt tests;
- Open Data Contract Standard output;
- Pydantic models;
- Neo4j/property-graph schema;
- ERD / interchange outputs;
- semantic output;
- RDF/OWL/SHACL/R2RML through the optional ontology stack.

### Reverse engineering
- compiled dbt manifests/catalogs;
- live warehouses through dbt adapters;
- SQL DDL;
- Mermaid / JSON Schema import paths;
- classification heuristics for staging, marts/rollups, SCD2, surrogate keys and relationships;
- confidence/review ledger rather than pretending every inferred mapping is authoritative.

### Drift / lifecycle
- model-vs-compiled-dbt drift detection;
- breaking/additive/cosmetic classification;
- CI gating;
- bounded reconcile for safe classes;
- stable identity designed to survive renames;
- model diff / subject-area workflows;
- Git branch + PR as the collaboration model.

### Ontology / governance
- ontology term alignment and pinned vocabulary sources;
- knowledge-graph exports;
- governance graph + adapter pattern;
- Collibra adapter / OpenLineage-related outputs;
- MCP tools and agent-mode access to model inspection/mutation.

## Architecture reconstruction

The public package boundaries expose a useful decomposition:

`core model IR`
`  -> validation / naming / identity`
`  -> emit-dbt`
`  -> emit-contract`
`  -> emit-pydantic`
`  -> emit-graph`
`  -> emit-erd`
`  -> emit-semantic`
`  -> reverse`
`  -> ontology`
`  -> governance/catalog adapters`
`  -> server/canvas`
`  -> LSP / VS Code`
`  -> MCP / agent tools`

The important architectural idea is not any specific Python package. It is **one authoritative model graph with multiple deterministic clients and compilers**.

## Owned product thesis

Add an **ADE Logical Model Compiler** as the canonical middle layer of ADE OS:

`BusinessFoundation / JTBD / ontology`
`        +`
`SourceCatalog / warehouse / dbt / DDL`
`        ↓`
`ModelDiscovery + MappingProposal`
`        ↓`
`Reviewed LogicalModel/v1`
`        ↓`
`ModelGraph + stable object identity`
`        ↓`
`GenerationPlan`
`   ├─ dbt`
`   ├─ Snowflake Semantic Views`
`   ├─ data contracts / DQ plan`
`   ├─ Pydantic / API contracts`
`   ├─ ERD / DiagramSpec`
`   ├─ governance/catalog metadata`
`   └─ graph / ontology exports`
`        ↓`
`compile / test / reconcile / verify`
`        ↓`
`ModelCompileReceipt + warehouse reconciliation evidence`

Reverse path:

`warehouse | dbt manifest | SQL DDL | existing semantic assets`
`        ↓`
`ReverseProposal + confidence/evidence`
`        ↓ human/agent review`
`LogicalModel revision`

Drift path:

`committed LogicalModel revision + observed warehouse/dbt/semantic state`
`        ↓`
`DriftReport`
`        ↓`
`safe reconcile proposal | breaking-change review | no-op`

## REA capability decision: MATCH / IMPROVE / NEW / OMIT

### MATCH

- Git-native declarative logical model.
- Visual ER authoring.
- CLI + IDE/LSP + agent/MCP surfaces over the same model.
- Entity/attribute/key/relationship/domain/subtype/subject-area primitives.
- dbt generation with contracts/tests.
- reverse from dbt/live warehouse/DDL.
- classified drift and CI gate.
- stable identity across renames.
- ontology references.
- deterministic multi-target compiler pattern.
- explicit review of ambiguous reverse-engineering decisions.

### IMPROVE

- Bind the logical model directly to ADE OS `BusinessOntology`, JTBD, metric definitions and source-authority rules from the Backbone lane.
- Treat every reverse-inferred relationship/key/business concept as an evidence-bearing proposal, never as silent truth.
- Separate physical schema, logical model, semantic model and business ontology instead of collapsing them.
- Add exact source/ontology/model/config/compiler digests to generation and reconciliation receipts.
- Add explicit data-grain semantics to every entity/model and metric dependency.
- Add generated-model complexity budgets and purpose receipts.
- Add test-portfolio quality coverage, not test-count scoring.
- Add deterministic source-to-target reconciliation evidence for counts, amounts, keys and business invariants.
- Add provider-neutral warehouse adapters beyond a dbt-only connection abstraction.
- Use ADE OS Data Quality and Data Diff engines as first-class validation targets.
- Generate Snowflake Semantic Views and agent/Cortex/MCP context from the same approved model revision.
- Connect DiagramSpec / Technical Visual Studio for architecture-quality diagrams while keeping the model graph authoritative.
- Route human-facing SQL/query inspection through Data Workbench rather than embedding a second database console.
- Integrate safe rename/refactor planning with the Warehouse Refactor Engine.
- Treat model mutations by AI as proposals subject to deterministic validation/policy/review; no agent self-approval of breaking changes.

### NEW owned capabilities

- `logical-model/v1` canonical IR.
- `model-object-id/v1` stable IDs independent of display names.
- `model-revision/v1` immutable revision + digest.
- `model-source-binding/v1` source/warehouse/dbt evidence bindings.
- `reverse-proposal/v1` with confidence, evidence and decision ledger.
- `model-generation-plan/v1` before any file/warehouse mutation.
- `model-compile-receipt/v1` exact generated-artifact evidence.
- `model-drift-report/v1` breaking/additive/cosmetic/unknown classification.
- `model-reconcile-plan/v1` safe vs approval-required changes.
- `model-impact-report/v1` downstream dbt/semantic/DQ/BI/agent impact.
- `model-complexity-receipt/v1` justification for generated layers/models.
- `model-test-portfolio-receipt/v1` business-risk coverage.
- canonical model graph exposed as governed Agent Work OS tools.

### OMIT / DEFER

- Modelith branding, UI trade dress, copy and assets.
- A feature-for-feature fork as our product strategy.
- Automatic acceptance of inferred relationships/keys/business mappings.
- Broad ontology/catalog integration before the core model/reverse/drift loop is proven.
- Direct production warehouse mutation in Phase A.
- Rebuilding every interchange format before dbt + Snowflake semantic + ERD paths are correct.
- Claiming semantic/business correctness merely because compilation succeeds.

## Phase A — canonical model IR + deterministic compiler

Build the smallest owned vertical slice on synthetic fixtures.

### Contracts

`LogicalModel`
- model ID / revision / canonical digest;
- entity collection;
- domains / reference data;
- relationships;
- subject areas;
- ontology/business-foundation references;
- source bindings;
- metadata extensions.

`Entity`
- stable object ID;
- display / physical names separated;
- business definition;
- grain;
- attributes;
- keys;
- source authority;
- optional ontology refs;
- lifecycle state.

`Attribute`
- stable object ID;
- logical name / physical mapping;
- logical type + target type hints;
- nullable;
- domain/ref-data binding;
- classification / sensitivity metadata;
- lineage/source evidence.

`Relationship`
- stable object ID;
- endpoint entity IDs;
- key mappings;
- cardinality / optionality;
- relationship semantics;
- evidence/provenance when reverse-inferred.

`ModelGenerationPlan`
- exact input model revision/digest;
- selected targets;
- every planned artifact path/object;
- expected dbt/semantic/DQ objects;
- warnings/unknowns;
- breaking/destructive flags;
- deterministic plan digest;
- no write authority by itself.

`ModelCompileReceipt`
- exact input model + generator/compiler revision;
- generated artifact hashes;
- validation/test results;
- output dependency graph;
- warnings/unknowns;
- terminal status;
- immutable receipt digest.

### Targets for Phase A

1. dbt project/model YAML + SQL skeleton for a bounded entity mapping.
2. Snowflake Semantic View specification/artifact using existing ADE semantic compiler primitives.
3. Mermaid/DiagramSpec ER representation.
4. DQ/test-plan output derived from keys/domains/relationships.

### Deterministic acceptance tests

- same canonical logical model -> same plan/artifact digests;
- YAML/object ordering cannot change semantic digest;
- rename with stable object ID preserves identity and produces explicit artifact rename impact;
- duplicate stable IDs fail;
- dangling relationship endpoints fail;
- foreign-key domain/type mismatch fails or produces explicit incompatible finding;
- missing entity grain blocks affected semantic metric generation;
- unresolved source authority remains unknown and blocks affected generated business logic;
- generated dbt relationship tests reference the exact relationship mapping;
- model compilation never mutates a warehouse in Phase A;
- plan is side-effect-free;
- stale model revision invalidates a compile/reconcile approval;
- AI-created proposal cannot bypass schema/semantic validation;
- generated artifact count above policy budget emits a complexity finding;
- generated test count alone cannot satisfy the quality gate.

## Phase B — reverse engineering

Input adapters:
1. dbt manifest/catalog;
2. SQL DDL / SQL AST;
3. live Snowflake first, then Databricks/BigQuery/Redshift as separate adapters.

Requirements:
- recover tables/columns/types/nullability/declared constraints;
- inspect dbt relationships/tests/refs/lineage;
- infer candidate keys/relationships only with confidence/evidence;
- classify staging/intermediate/mart/rollup entities through configurable rules;
- preserve every decision in a review ledger;
- never silently replace the approved logical model.

Output is `ReverseProposal`, not an authoritative model until reviewed/accepted.

## Phase C — drift / diff / reconcile

Compare:
- logical model vs dbt manifest;
- logical model vs live warehouse;
- logical model vs generated semantic artifacts;
- approved business foundation vs logical model.

Classify findings:
- `breaking`;
- `additive`;
- `cosmetic`;
- `semantic_conflict`;
- `source_authority_conflict`;
- `unknown`.

Only explicitly configured safe classes may be auto-proposed for reconciliation. Breaking/semantic/source-authority conflicts require review.

## Phase D — visual modeler + IDE

- browser canvas backed by the canonical model graph;
- entity/relationship/domain editor;
- subject-area views;
- impact/drift overlays;
- reverse-review panel;
- generated-artifact preview;
- VS Code extension/LSP using the same backend contracts.

The canvas is a client, never a second state store.

## Phase E — agent-native modeling

Governed tools:
- `list_entities`;
- `get_entity`;
- `explain_relationship`;
- `explain_model_impact`;
- `reverse_source`;
- `explain_drift`;
- `propose_entity`;
- `propose_attribute`;
- `propose_relationship`;
- `plan_generation`;
- `plan_reconcile`.

Agent mutations remain proposals until deterministic checks and policy/review gates pass.

## Phase F — enterprise compiler targets

- ODCS / contract export;
- Pydantic/API schemas;
- governance/catalog adapters;
- knowledge graph/RDF lane where useful;
- Power BI / Excel semantic compatibility artifacts;
- OpenLineage / lineage event output;
- provider-neutral semantic targets beyond Snowflake.

## Differentiation vs simply adopting Modelith

Modelith is already a strong open-source data modeler. Our reason to build an owned layer is not to redraw its UI. The ADE OS differentiation is the **closed loop from business intent to model to warehouse to semantic/AI consumers to observed reconciliation evidence**:

`JTBD/business ontology`
` -> approved logical model`
` -> generated warehouse/dbt/semantic/DQ artifacts`
` -> real execution`
` -> data-quality + reconciliation evidence`
` -> drift/change impact`
` -> governed repair/review`

That closes gaps that a modeling tool alone cannot prove:
- whether the business definition is correct;
- whether source authority is correct;
- whether generated transformations reconcile to source facts;
- whether metrics exposed to BI/AI match governed definitions;
- whether a proposed schema/model change is safe across downstream assets;
- whether an agent was authorized to make the change.

## Build-vs-reuse policy

Upstream is Apache-2.0. Direct reuse is legally possible subject to applicable license/notice obligations, but architecture ownership still matters.

Default:
- keep ADE OS contracts and canonical IR independently owned;
- treat Modelith as a donor/comparator/reference implementation;
- reuse upstream source only where it clearly reduces commodity engineering and provenance/license obligations are recorded;
- never make our business-foundation, semantic, DQ or evidence architecture depend on Modelith-specific internal object layouts;
- preserve exact upstream SHA and notices for any intentionally reused code.

Possible commodity reuse candidates after review:
- SQL import parsing patterns;
- dbt artifact parsing patterns;
- selected interchange exporters/importers;
- IDE/LSP integration patterns;
- ontology adapters.

Do not reuse branding/assets/UI trade dress.

## Current truthful state

`SOURCE = done`
`PUBLIC EVIDENCE = first-pass done`
`UPSTREAM IDENTITY/LICENSE/SHA = pinned`
`ARCHITECTURE RECONSTRUCTION = first-pass done`
`INTERNAL DEDUPE = done`
`PRODUCT ROUTING = ADE OS module`
`PHASE-A CONTRACT = specified`
`IMPLEMENTATION = not started`
`LIVE WAREHOUSE CERTIFICATION = none`
`PRODUCTION = none`

## Next engineering action

Implement Phase A in a bounded feature branch after the current research branch is reviewed:

`feature/logical-model-compiler-phase-a`

Start with:
1. canonical model schemas + hashing;
2. validation;
3. synthetic Customer/Order/Product fixture;
4. deterministic dbt + Snowflake semantic + DiagramSpec + DQ generation plan;
5. receipts + negative tests;
6. exact-SHA CI.

Then add reverse/drift before investing heavily in canvas polish.
