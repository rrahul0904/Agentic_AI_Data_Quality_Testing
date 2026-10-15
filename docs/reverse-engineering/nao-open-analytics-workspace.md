# nao / Open Analytics Workspace — Reverse Engineering Dossier

Status: `RESEARCHED -> SPECIFIED -> SHIPPING-CONTRACT-READY`

Canonical program: **TECH-SEMANTIC / Agentic Data Engineering OS**

Source issue: #31

Source inputs:
- LinkedIn post supplied by the user: https://lnkd.in/p/gBkNJ4WA
- Public repository: https://github.com/getnao/nao
- Product/docs: https://getnao.io/

## 1. Why this is a donor, not a new product

The current ADE mainline already contains a governed semantic platform: canonical semantic contracts, Snowflake Semantic View tooling, dbt, Cortex Agent/MCP contracts, governed chart execution, Power BI/Excel parity tooling, evidence receipts, and local-first runtime packaging.

nao overlaps that product boundary heavily. The useful outcome is therefore **capability absorption into ADE**, not a clone.

## 2. Observed product thesis

The public nao position is that analytics should not be locked to one model/vendor harness. Its differentiating boundary is:

1. context belongs to the data team and can live as files/Git;
2. the analytics UI is self-hostable and model/provider agnostic;
3. generated analytics remain inspectable and editable by humans;
4. SQL/results/provenance remain visible instead of being hidden behind prompts;
5. the context and agent can be tested/versioned before broad deployment.

This turns the product from "chat with data" into a governed analytics workspace whose semantics and artifacts survive model replacement.

## 3. Public workflow reconstruction

Observed public flow:

`nao init -> configure project/context -> nao sync -> context filesystem -> agent question -> discover context -> SQL/semantic query -> execute via connector -> result cache -> table/chart/story -> human inspection/editing -> feedback/evaluation`

Public docs and repository material show support for multiple databases and LLM providers, local/self-hosted Docker operation, MCP/skills, natural-language analytics, native visualization, test/evaluation workflows, and Git-backed context.

A current public semantic-layer design also describes a compile-only MetricFlow approach: semantic query -> compile SQL -> execute through the existing platform SQL path rather than bypassing normal execution controls.

## 4. Architecture reconstruction

### Context plane
- project configuration
- Git/file-system context
- database metadata
- repos/docs/rules
- semantic definitions
- skills/MCP
- test cases

### Agent/control plane
- provider/model routing
- context discovery
- bounded tool selection
- semantic-query planner
- SQL executor
- result cache
- feedback/evaluation

### Visualization plane
- table result
- editable chart
- map/story composition
- visible SQL/provenance
- saved/versioned analytics artifact

### Runtime plane
- local CLI
- backend API
- frontend chat/workspace
- self-hosted Docker/runtime
- optional persistent database

## 5. Public feedback signals from the supplied LinkedIn thread

The feedback is unusually useful because it directly identifies product risks rather than just praise.

### Metric-definition consistency is the real problem
A commenter argues that different executives will still get conflicting numbers unless metrics/semantics are centrally defined. This reinforces ADE's existing canonical semantic-contract architecture and is a reason **not** to adopt free-form dashboard generation as the source of truth.

### Git-owned definitions are valuable, but review ownership matters
Another commenter highlights that Git changes the ownership model and raises the governance question: who actually reviews definitions? ADE should therefore bind analytics context changes to review/evidence, not merely store them in Git.

### SQL auditability is more important than the dashboard shell
The thread explicitly calls out the value of seeing the SQL behind a chart. In ADE, every visual artifact should expose or reference the exact governed query/result fingerprint and provenance.

### LLM agnosticism can be superficial
One commenter correctly notes that model lock-in can simply move into a harness-specific context structure. ADE should use a provider-neutral context manifest and semantic contract instead of shaping the context around one model SDK.

### Small businesses may prefer one tightly integrated tool
A counterpoint is that model/vendor lock-in can be an acceptable convenience for very small teams. ADE should not optimize the core architecture around this case; instead, a simplified single-model preset can sit above a provider-neutral core.

## 6. Competitive/internal audit against ADE

### Already stronger in ADE
- canonical semantic contract as source of truth
- deterministic semantic release manifests/hashes
- Snowflake Semantic View compilation
- Cortex Agent + governed MCP contracts
- Power BI + Excel parity contracts
- approval-bound execution
- evidence receipts and exact-SHA certification
- synthetic enterprise workload and cross-domain portability
- dbt and governed chart execution
- local-first deployment/security boundaries

### nao donor gaps worth absorbing
- explicit Git-owned analytics-context workspace UX
- provider/model switching as a first-class user feature
- context/version evaluation workflow oriented to analytics questions
- editable chart/story artifacts attached directly to agent results
- more direct SQL/provenance inspection in the analyst experience
- unified conversational workspace around context + query + visualization + story
- simpler self-service onboarding for analytics consumers

## 7. Product boundary to build in ADE

Working name: **Open Analytics Workspace**

Canonical flow:

`Git-owned context -> governed semantic contract -> question plan -> semantic/query plan -> bounded read-only execution -> auditable result -> editable visualization -> saved story -> evaluation receipt`

This is not a separate platform. It is an ADE product surface on top of the existing semantic/runtime/evidence foundations.

## 8. Phase A contracts

### AnalyticsContextManifest
Required fields:
- context_id
- source_type
- source_uri
- exact_revision_sha
- semantic_contract_sha
- file_manifest_hash
- generated_at
- freshness_state
- allowed_model_routes
- security_policy_ref

### AnalyticsQuestionPlan
Required fields:
- question
- normalized_intent
- referenced_metrics
- referenced_dimensions
- context_evidence_refs
- security_context
- required_execution_mode
- confidence
- unresolved_terms

### SemanticQueryPlan
Required fields:
- planner_version
- semantic_contract_sha
- metrics
- dimensions
- filters
- time_range
- compiled_query_hash
- read_only
- connector_ref
- security_context
- unresolved_reasons

### VisualizationArtifact
Required fields:
- artifact_id
- query_plan_hash
- result_signature
- visualization_type
- presentation_config
- semantic_bindings
- provenance_refs
- created_at
- edited_at

Presentation edits must not silently change semantic bindings or execution fingerprints.

### AnalyticsStory
Required fields:
- story_id
- title
- artifact_refs
- narrative_sections
- context_revision_sha
- semantic_contract_sha
- result_signatures
- provenance_refs
- version

### EvaluationCase / EvaluationReceipt
Evaluation must bind:
- exact context revision
- semantic contract SHA
- question
- expected semantic entities
- optional expected result signature/shape
- policy/security context
- actual plan/result signatures
- deterministic PASS/FAIL reasons

### ModelRoute
Required fields:
- provider
- model
- capability class
- policy profile
- allowed tools
- max budget/time
- fallback route

Changing provider/model must not change execution authorization or semantic source of truth.

## 9. Phase A acceptance tests

1. Given a fixed context revision and governed banking semantic contract, the same business question resolves to the same semantic entities regardless of LLM provider route.
2. Unknown metric/dimension fails closed rather than inventing SQL.
3. Every executed query is read-only and passes the existing ADE SQL guard.
4. A chart artifact contains exact query-plan hash, result signature, context SHA, and semantic-contract SHA.
5. Editing chart title/type/format preserves semantic bindings and query/result fingerprint unless the user explicitly requests a new query.
6. A story can be saved/reloaded and every component resolves to retained provenance.
7. Evaluation replay against the same revision is deterministic.
8. Changing context revision invalidates certification until the case is rerun.
9. Cancellation/restart never marks partial execution as certified.
10. Tokens/secrets/reasoning traces are not persisted in receipts.
11. Security/RLS context is preserved from question plan through execution and visualization evidence.
12. Local fixture path works with no external warehouse or LLM credentials.

## 10. Failure modes to test

- stale Git revision
- missing semantic artifact
- context and semantic contract hash mismatch
- unsupported chart definition
- result schema drift
- ambiguous metric name
- mutating SQL attempt
- connector timeout
- result-cache corruption
- provider/model unavailable
- fallback route changes policy surface
- cancelled story generation
- replay against changed context
- unauthorized cross-tenant/security-context reuse

## 11. Clean-room and licensing rules

The public repo advertises Apache-2.0, but its contributor documentation also states that some files are separately marked as Enterprise Edition.

Rules for this donor:
- do not copy or derive from EE-marked files;
- prefer independent ADE-native contracts and implementation;
- if any Apache-licensed OSS code is reused directly, preserve required notices and record provenance;
- do not copy branding, visual identity, private-service behavior, or proprietary enterprise features;
- do not claim parity with nao or Claude Dashboards without executed comparative evidence.

## 12. Roadmap status

- SOURCE: complete
- EVIDENCE: complete for current public surfaces and supplied LinkedIn comments
- RECONSTRUCTION: complete for the first donor slice
- COMPETITIVE/INTERNAL AUDIT: complete
- PRODUCT BOUNDARY: complete
- CONTRACTS/ACCEPTANCE TESTS: specified
- SHIPPING CONTRACT: companion machine-readable contract in this branch
- IMPLEMENTATION: not started in this donor PR
- RUNTIME/UAT/DEPLOYMENT: not claimed

## 13. First implementation slice after WIP gate

Build one local, fixture-backed vertical slice on the existing banking/reference semantic contract:

1. open Analytics Workspace;
2. ask a governed business question;
3. create `AnalyticsQuestionPlan`;
4. resolve exact semantic context;
5. create `SemanticQueryPlan`;
6. execute through existing read-only ADE connector path;
7. render table + chart;
8. edit presentation only;
9. save an `AnalyticsStory`;
10. run one `EvaluationCase`;
11. emit exact SHA/context/query/result/evaluation receipt;
12. replay after restart and compare receipts.

Only after this slice passes exact-head CI should we add live provider switching, live Snowflake, broader visual types, sharing, and multi-user collaboration.
