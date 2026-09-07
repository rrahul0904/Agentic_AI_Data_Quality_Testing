# MASTER IMPLEMENTATION PROMPT — AGENTIC AI DATA QUALITY & PIPELINE ASSURANCE PLATFORM

You are the principal architect, staff engineer, data-platform engineer, AI engineer, QA lead, security engineer, and product engineer responsible for evolving the existing **ADE Test Control Tower v0.2** into a working **Agentic AI Data Quality & Pipeline Assurance Platform**.

This is an implementation assignment.

Do not merely produce architecture diagrams, TODO lists, mock screens, pseudocode, or documentation.

You must inspect the existing repository, understand what already works, preserve useful implementation, design the target architecture, implement the highest-value working vertical slice end-to-end, test it thoroughly, and leave the repository in a coherent state that can continue toward the enterprise target architecture.

---

# 0. PRIMARY PRODUCT OBJECTIVE

We are no longer building merely:

> a dbt/Airflow test runner.

We are building:

> **An Agentic AI Data Quality & Pipeline Assurance Platform that continuously understands, tests, reconciles, diagnoses, explains, optimizes and certifies enterprise data pipelines from source to consumption using business-aware, evidence-grounded AI agents.**

The platform must eventually support:

- Airflow
- dbt Core
- dbt Cloud
- Snowflake
- BigQuery
- Amazon Redshift
- Databricks

The architecture must allow additional sources/targets later without rewriting the quality engine:

- Oracle
- SQL Server
- PostgreSQL
- MySQL
- Teradata
- S3
- ADLS
- GCS
- Kafka
- Salesforce
- APIs
- files
- additional warehouses/lakehouses

The core user workflow is:

```text
BUSINESS INTENT
      ↓
CONTEXT INTELLIGENCE
      ↓
BUSINESS QUALITY CONTRACT
      ↓
TECHNICAL / TRANSFORMATION UNDERSTANDING
      ↓
AI-GENERATED QUALITY INTENT
      ↓
GROUNDING / EVIDENCE VALIDATION
      ↓
QUALITY EXECUTION PLANNER
      ↓
DETERMINISTIC EXECUTION
      ↓
SOURCE-TO-TARGET RECONCILIATION
      ↓
EVIDENCE COLLECTION
      ↓
FAILURE DETECTION
      ↓
EVIDENCE-GROUNDED RCA
      ↓
IMPACT ANALYSIS
      ↓
REMEDIATION RECOMMENDATION
      ↓
APPROVAL / POLICY GATE
      ↓
RETEST
      ↓
CERTIFICATION
```

---

# 1. FIRST RULE: INSPECT BEFORE REBUILDING

Before modifying architecture:

1. Read the repository end-to-end.
2. Read:
   - README
   - architecture documentation
   - runbook
   - changelog
   - version
   - backend models
   - API routes
   - services
   - existing dbt implementation
   - existing Airflow implementation
   - lineage implementation
   - current UI
   - tests
   - scripts
3. Run the existing test suite.
4. Start the application.
5. Verify existing dbt execution.
6. Verify existing Airflow execution.
7. Identify working components worth retaining.
8. Create a concise CURRENT_STATE.md documenting:
   - what is already real,
   - what is partial,
   - what is prototype-only,
   - what needs replacement,
   - what can be reused.

Do NOT throw away working dbt/Airflow execution simply to adopt a new architecture.

Preserve and evolve useful code.

---

# 2. EXISTING FOUNDATION TO PRESERVE WHERE APPROPRIATE

The existing system already demonstrates useful primitives:

- Python
- FastAPI
- SQLAlchemy
- real dbt-core execution
- dbt artifact parsing
- dbt Cloud client foundation
- Airflow REST API interaction
- Airflow execution
- asynchronous orchestration
- project/job/DAG persistence
- lineage extraction
- raw execution evidence
- run result persistence
- DuckDB local demonstration capability
- Snowflake adapter foundation

Use these as starting assets.

---

# 3. TARGET PRODUCT ARCHITECTURE

Design toward the following logical architecture:

```text
┌───────────────────────────────────────────────────────────────┐
│                  EXPERIENCE / CONTROL TOWER                  │
│                                                               │
│ Home | Data Products | Pipelines | Quality | Contracts       │
│ Business Context | Lineage | Evidence | Incidents            │
│ Agents | Certifications | Cost | Administration              │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                     FASTAPI CONTROL PLANE                    │
│                                                               │
│ Organizations / Connections / Datasets / Pipelines           │
│ Contracts / Rules / Runs / Agents / Evidence / Incidents     │
│ Policies / Costs / Certifications / Audit                    │
└──────────────────────────────┬────────────────────────────────┘
                               │
          ┌────────────────────┼─────────────────────┐
          ▼                    ▼                     ▼
 CONTEXT INTELLIGENCE   EVIDENCE INTELLIGENCE    LINEAGE
          │                    │                     │
          └────────────────────┼─────────────────────┘
                               ▼
                     GROUNDED REASONING
                               │
                               ▼
                     AGENT SUPERVISOR
                               │
        ┌──────────────────────┼───────────────────────┐
        ▼                      ▼                       ▼
 Metadata Agent        Transformation Agent      Quality Agent
 Business Agent        Mapping Agent             RCA Agent
 Lineage Agent         Impact Agent              Remediation Agent
                               │
                               ▼
                      QUALITY INTENT
                               │
                               ▼
                QUALITY EXECUTION PLANNER
                               │
        ┌──────────────────────┼────────────────────────┐
        ▼                      ▼                        ▼
 Scale Intelligence       Cost Intelligence      Change Intelligence
        │                      │                        │
        └──────────────────────┼────────────────────────┘
                               ▼
                     QUALITY RULE ENGINE
                               │
                               ▼
                     DIALECT COMPILERS
                               │
         ┌─────────────┬───────┼─────────┬────────────┐
         ▼             ▼       ▼         ▼            ▼
    Snowflake       BigQuery Redshift Databricks    dbt
                               │
                               ▼
                    PIPELINE ADAPTERS
                               │
                    Airflow / dbt / dbt Cloud
                               │
                               ▼
                      EVIDENCE STORE
                               │
                               ▼
                  RCA / IMPACT / REMEDIATION
```

---

# 4. TARGET TECHNOLOGY STACK

Use this as the architectural baseline.

## Backend

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic

## Database

Production architecture:

- PostgreSQL
- pgvector

For the immediate demo, SQLite may remain temporarily only if replacing it would endanger the working vertical slice.

However:

- repository interfaces must be database-agnostic,
- schema must be PostgreSQL compatible,
- migration strategy must be documented,
- SQLite-specific assumptions must not spread.

## Frontend

Move toward:

- Next.js
- React
- TypeScript
- Tailwind compiled locally
- Radix primitives
- custom product design system
- TanStack Query
- TanStack Table
- React Flow
- Apache ECharts

The result must look like a serious enterprise data platform.

Do not produce generic AI-dashboard visual design.

## Workflow / orchestration

Target architecture:

- Temporal for durable long-running workflows.

Immediate client-demo implementation may retain existing asyncio orchestration if Temporal cannot be introduced safely within the current implementation window.

If retained temporarily:

create clean workflow abstractions so Temporal can replace it later.

## SQL intelligence

Use:

- SQLGlot

for:

- parsing,
- AST generation,
- dialect handling,
- transformation understanding,
- SQL comparison,
- column extraction,
- filter detection,
- join detection,
- aggregation detection,
- CASE logic,
- window logic,
- transformation lineage.

## Storage

Architecture:

- PostgreSQL for structured operational data
- pgvector for semantic retrieval
- S3-compatible object storage for large evidence
- Redis for cache/transient coordination

## Lineage

Use:

- current lineage implementation where useful,
- evolve toward OpenLineage-compatible entities/events.

## Observability architecture

Design for:

- OpenTelemetry
- Prometheus
- Grafana
- structured logs
- Sentry

Do not block demo completion on deploying the entire observability ecosystem.

---

# 5. NON-NEGOTIABLE AI PRINCIPLE

AI MUST NOT determine deterministic truth.

AI performs:

- business-language interpretation,
- context discovery,
- mapping proposals,
- transformation understanding,
- test generation,
- missing-test detection,
- source-target mapping suggestions,
- RCA hypothesis generation,
- impact analysis,
- explanation,
- remediation recommendation,
- optimization suggestions.

Deterministic systems perform:

- SQL execution,
- row count,
- aggregate calculation,
- null checks,
- uniqueness checks,
- hash comparison,
- schema comparison,
- reconciliation,
- Airflow state checks,
- dbt test state checks,
- pass/fail evaluation,
- tolerance evaluation.

Rule:

> **AI decides WHAT should be tested. Deterministic engines prove WHETHER it passed.**

Never violate this separation.

---

# 6. CONTEXT INTELLIGENCE — REQUIRED

Context Intelligence exists to prevent agents from inventing meaning.

It answers:

> What does this business concept mean, and what trustworthy context applies to the current task?

Implement canonical models such as:

```text
BusinessConcept
BusinessDefinition
BusinessDomain
BusinessGlossaryEntry
DataProduct
Dataset
Column
Pipeline
Transformation
QualityContract
ContextSource
ContextVersion
ContextRelationship
ContextPackage
```

Each context object must support provenance:

```text
source
source_type
version
owner
effective_date
last_updated
approval_status
authority_level
retrieved_at
```

Context retrieval must be hybrid.

Do NOT implement Context Intelligence as:

```text
question → vector search → LLM
```

Use the correct retrieval mechanism.

Examples:

Structured metadata:
→ relational query

Business documentation:
→ semantic/vector retrieval

Lineage:
→ graph traversal

dbt:
→ manifest/catalog/run artifacts

Airflow:
→ REST metadata

SQL:
→ SQLGlot AST

Live schema:
→ warehouse adapter

Git:
→ repository state / diff

The output to an agent should be a structured:

```text
ContextPackage
```

containing:

- business concept
- authoritative definition
- datasets
- columns
- mappings
- transformations
- source
- target
- pipelines
- quality contracts
- owners
- SLA
- tolerance
- citations/provenance
- conflicts
- freshness
- confidence classification

If context is missing:

DO NOT GUESS.

Return:

```text
INSUFFICIENT_CONTEXT
```

and request/collect additional evidence.

---

# 7. EVIDENCE INTELLIGENCE — REQUIRED

Evidence Intelligence is a first-class subsystem.

It answers:

> What actually happened, and what proves the claim?

Create canonical:

```text
Evidence
EvidenceType
EvidenceSource
EvidenceRelationship
EvidenceBundle
AgentClaim
ClaimEvidenceLink
VerificationResult
```

Evidence sources include:

## Warehouse

- executed SQL
- query ID
- timestamp
- bytes scanned if available
- rows scanned
- result
- aggregates
- hashes
- exception rows
- schema
- statistics
- query plan
- query history

## dbt

- manifest.json
- catalog.json
- run_results.json
- compiled SQL
- model metadata
- test output
- source freshness
- execution status

## Airflow

- DAG run
- task states
- task duration
- retries
- task logs/references
- schedules
- dependency information

## Code

- file
- commit
- PR
- diff
- changed SQL
- changed DAG
- changed config

## Context

- business contract
- glossary definition
- mapping
- approved rule
- lineage relationship

Small evidence:
→ relational database

Large artifacts:
→ object store abstraction

For immediate demo, local filesystem may emulate object storage through a proper storage interface.

---

# 8. CLAIM-EVIDENCE GROUNDING GATE

No important agent conclusion may bypass grounding.

Implement a GroundingGateway.

Agent produces:

```text
AgentClaim
```

not naked conclusions.

Example:

```text
claim:
"The revenue discrepancy was caused by fact_revenue.sql
excluding SHIPPED records."
```

It must link:

```text
supporting_evidence[]
contradictory_evidence[]
```

Statuses:

```text
SUPPORTED
PARTIALLY_SUPPORTED
UNVERIFIED
CONFLICTED
REJECTED
```

Minimum rules:

```python
if required_context_missing:
    block_action()

if deterministic_claim and supporting_evidence_empty:
    status = UNVERIFIED

if contradictory_evidence_present:
    status = CONFLICTED

if direct_reproducible_evidence_present:
    status = SUPPORTED
```

Agents may say:

```text
UNKNOWN
INSUFFICIENT_EVIDENCE
```

This is desirable.

Agents MUST NOT fabricate certainty.

---

# 9. EVIDENCE AUTHORITY

Implement evidence ranking.

Example:

## Tier 1

Deterministic execution evidence:

- database result
- reconciliation
- hash
- Airflow state
- dbt result
- schema metadata

## Tier 2

Authoritative enterprise definitions:

- approved contract
- business glossary
- certified mapping
- approved lineage

## Tier 3

Engineering evidence:

- SQL
- dbt code
- DAG code
- Git diff
- runbook

## Tier 4

Historical evidence:

- previous incidents
- prior RCA
- anomaly history

## Tier 5

LLM inference

Higher tiers override unsupported lower-tier inference.

LLM statements themselves are NEVER evidence.

---

# 10. BUSINESS QUALITY CONTRACTS

Users must be able to express quality requirements in business language.

Example input:

```text
Business Concept:
Net Revenue

Definition:
Gross sales minus discounts, refunds and taxes.

Rules:
Cancelled orders must not contribute revenue.

SLA:
Daily by 6 AM.

Tolerance:
0.1%

Criticality:
Tier 1
```

Convert into a structured versioned QualityContract.

Example representation:

```yaml
dataset: finance.fact_revenue

business:
  concept: Net Revenue
  domain: Finance
  criticality: TIER_1

grain:
  - order_id

sla:
  freshness: "06:00"

rules:

  - id: revenue_not_null
    dimension: completeness

  - id: cancelled_orders_zero
    dimension: business_rule

  - id: source_target_reconciliation
    dimension: accuracy
    tolerance: 0.001
```

Contracts require:

- version
- owner
- approval state
- source/provenance
- effective date
- rule lineage

---

# 11. QUALITY TAXONOMY

The canonical Quality Rule Engine must support architecture for all of the following.

## Schema

- existence
- unexpected columns
- data type
- length
- precision
- scale
- nullability
- PK
- FK
- schema drift
- default
- partition
- clustering

## Completeness

- null checks
- missing records
- missing partitions
- missing dates
- incomplete batches
- source-target completeness
- late-arriving records

## Uniqueness

- primary key
- composite key
- duplicates
- business-key duplicates
- duplicate events
- replay detection

## Validity

- allowed values
- regex
- range
- enums
- date validity
- reference lookup
- domain rules
- country/currency/etc.

## Accuracy

- source-of-truth comparison
- cross-system validation
- derived columns
- reference data
- calculation correctness

## Consistency

- cross-column
- cross-table
- cross-system
- currency
- units
- dates
- hierarchy

## Referential integrity

- orphans
- parent existence
- FK integrity
- hierarchy
- dimensional integrity

## Freshness / timeliness

- source freshness
- table freshness
- partition freshness
- load SLA
- pipeline latency
- late file/event

## Volume

- row counts
- spikes
- drops
- historical deviation
- partition volume

## Distribution / statistics

- min/max
- mean
- median
- percentiles
- standard deviation
- cardinality
- distinct count
- category distribution
- drift

## Anomaly

Architecture for:

- z-score
- IQR
- EWMA
- seasonal comparison
- change point
- forecast deviation

Do not over-engineer advanced ML during the first demo.

## Transformation correctness

This is critical.

Support test generation around:

- CASE
- JOIN
- FILTER
- GROUP BY
- aggregations
- windows
- deduplication
- SCD1
- SCD2
- currency conversion
- timezone conversion
- date derivation
- allocation
- revenue recognition
- lookups
- surrogate keys
- conditional mappings
- pivot/unpivot
- incremental processing
- CDC

## Pipeline correctness

Also support:

- idempotency
- retries
- backfills
- partial failures
- incremental correctness
- CDC
- watermark handling
- late arrivals
- duplicate replay
- checkpoint recovery
- restart behavior
- schema evolution
- data loss across retry

The product is not merely "data quality."

It is also:

> **pipeline correctness and pipeline assurance.**

---

# 12. QUALITY RULE ENGINE

Create a canonical platform-independent QualityRule model.

Example:

```yaml
id: QR-1001

dataset:
  finance.fact_revenue

dimension:
  accuracy

type:
  transformation_reconciliation

expression:
  net_revenue =
    gross_revenue -
    discount -
    refund -
    tax

grain:
  - order_id

tolerance:
  percentage: 0.001

severity:
  P1

evidence:
  retain_exceptions: true
```

The same logical rule must compile through adapter/compiler layers.

Do not create separate conceptual quality systems for:

```text
Snowflake
BigQuery
Redshift
Databricks
```

Instead:

```text
QualityRule
      ↓
RuleCompiler
      ↓
Dialect-specific SQL
```

Allow dbt test compilation as another backend where appropriate.

---

# 13. SQL EXECUTION

All pass/fail quality execution must remain deterministic.

Generate SQL from canonical rules.

Store:

```text
logical rule
generated SQL
dialect
execution parameters
query ID
result
exceptions
metrics
timestamp
evidence links
```

Generated SQL must be inspectable in the UI.

Never hide SQL behind an opaque agent response.

---

# 14. SOURCE / TARGET ADAPTER SDK

Define a strict adapter interface.

Example:

```python
class DataPlatformAdapter(ABC):

    test_connection()

    discover_metadata()

    get_schema()

    get_table_stats()

    get_partitions()

    get_row_count()

    sample_data()

    execute_query()

    explain_query()

    estimate_query_cost()

    get_query_history()

    get_lineage_metadata()

    cancel_query()
```

Build adapter contracts for:

- Snowflake
- BigQuery
- Redshift
- Databricks

Reuse existing:

- DuckDB
- Snowflake code

where appropriate.

For the immediate demo:

FULLY IMPLEMENT AND TEST:

- DuckDB

and, if working credentials are available:

- Snowflake

For:

- BigQuery
- Redshift
- Databricks

implement:

- complete interface,
- configuration schema,
- dependency structure,
- connection validation logic where possible,
- dialect compiler tests,
- unit/contract tests with mocks.

Do NOT claim adapters have been live-tested when they have not.

Document exact certification status for every adapter.

---

# 15. PIPELINE ADAPTER SDK

Do not tightly couple the intelligence layer to Airflow.

Create:

```python
class PipelineAdapter(ABC):

    test_connection()

    discover_pipelines()

    discover_tasks()

    get_dependencies()

    trigger_pipeline()

    get_run()

    get_task_states()

    get_logs()

    retry_task()

    cancel_run()

    get_schedule()
```

Implement:

- AirflowAdapter
- DbtCoreAdapter
- DbtCloudAdapter

Preserve current working Airflow/dbt integrations.

Future-ready interfaces:

- MWAA
- Cloud Composer
- Astronomer
- Databricks Workflows
- Dagster
- Prefect
- ADF

Do not implement every future orchestrator now.

---

# 16. AIRFLOW

Current local per-project Airflow provisioning may stay for:

- development
- sandbox
- integration tests
- demo fallback

Production architecture should support connection to:

- self-hosted Airflow
- MWAA
- Cloud Composer
- Astronomer

through the adapter.

The platform is a control plane.

It should not require owning the customer's Airflow installation.

---

# 17. DBT

Preserve real dbt execution.

Support:

- dbt Core
- dbt Cloud

Ingest:

- manifest.json
- catalog.json
- run_results.json
- compiled SQL
- sources
- models
- tests
- metrics
- exposures where available

Use these for:

- lineage
- transformation intelligence
- quality coverage
- evidence
- RCA

---

# 18. TRANSFORMATION INTELLIGENCE

Implement a Transformation Analyzer.

Input:

```text
SQL / dbt compiled SQL
```

Use SQLGlot to derive structured information:

```text
inputs
outputs
columns
joins
filters
CASE expressions
aggregates
GROUP BY
windows
deduplication
calculated columns
dependencies
```

Example:

```sql
CASE
  WHEN country = 'US'
  THEN amount
  ELSE amount * exchange_rate
END
```

should produce candidate checks such as:

```text
US rows remain unchanged
non-US rows require FX rate
FX rate > 0
converted amount equals amount * rate
supported currency
null FX rejected
```

Agent proposes quality intent.

Deterministic SQL proves it.

---

# 19. AGENT ARCHITECTURE

Do NOT create one giant agent.

Create an Agent Supervisor coordinating specialized typed agents.

Minimum architecture:

```text
Supervisor
    │
    ├── Metadata Agent
    ├── Business Context Agent
    ├── Lineage Agent
    ├── Transformation Agent
    ├── Mapping Agent
    ├── Quality/Test Generation Agent
    ├── Execution Planning Agent
    ├── Evidence Agent
    ├── RCA Agent
    ├── Impact Agent
    └── Remediation Agent
```

For the first vertical slice, fully implement the highest-value five:

1. Context Agent
2. Transformation Agent
3. Quality Agent
4. Evidence Agent
5. RCA Agent

Other agents may initially be smaller domain services but interfaces must be clean.

---

# 20. AGENT IMPLEMENTATION RULE

Do NOT make a heavyweight AI framework the architectural center of the product.

Prefer:

```text
Typed Python domain service
+
Pydantic contracts
+
LLM gateway
+
workflow orchestration
+
deterministic tools
```

Agents must use structured outputs.

Example:

```python
class AgentClaim(BaseModel):
    statement: str
    claim_type: ClaimType
    supporting_evidence: list[UUID]
    contradictory_evidence: list[UUID]
    status: ClaimStatus
```

The LLM is replaceable infrastructure.

Our domain model is the product.

---

# 21. LLM GATEWAY AND AI COST CONTROL

Implement a provider-neutral LLM Gateway abstraction.

Do not scatter vendor client calls throughout the codebase.

Gateway responsibilities:

- provider abstraction
- model registry
- use-case routing
- structured output
- retry
- timeout
- token accounting
- request cost accounting
- prompt version
- response provenance
- rate limits
- fallback
- caching
- redaction
- tool permissions
- audit

Design routing to reduce AI cost.

Use high-capability reasoning only where needed:

```text
Business interpretation
RCA
Complex mapping
Complex transformation reasoning
```

Use less expensive models or deterministic code for:

```text
classification
formatting
simple extraction
summaries
basic SQL categorization
metadata normalization
```

If the runtime supports subagent/model routing, use the least expensive model that reliably completes each task.

Never use an LLM where deterministic code can solve the problem.

Cache context and structured interpretations by:

```text
input hash
code version
schema version
prompt version
model version
```

Do not repeatedly spend tokens interpreting unchanged SQL or unchanged business contracts.

---

# 22. QUALITY EXECUTION PLANNER

This is critical for terabyte-scale operation.

Agents create:

```text
QUALITY INTENT
```

They DO NOT directly run arbitrary expensive SQL.

QualityExecutionPlanner determines:

```text
how should this rule be proven safely?
```

Inputs:

- table size
- row estimate
- partitions
- clustering
- target platform
- changed partitions
- last certification
- historical metrics
- business criticality
- SLA
- tolerance
- query cost
- test type
- available compute
- confidence requirement

Planner strategies:

```text
metadata-only
full scan
incremental scan
partition scan
aggregate reconciliation
sampling
bucket hashing
hierarchical hashing
record-level comparison
cached evidence
historical baseline
```

---

# 23. DATA LOCALITY — NON-NEGOTIABLE

Never pull massive datasets into FastAPI or Python for ordinary testing.

Rule:

> **Move the test to the data. Do not move the data to the accelerator unless the result is intentionally small.**

Snowflake computes Snowflake data.

BigQuery computes BigQuery data.

Redshift computes Redshift data.

Databricks computes Databricks data.

The accelerator receives:

- metrics
- counts
- hashes
- statistics
- query metadata
- exception records

NOT billions of raw rows.

---

# 24. SOURCE-TO-TARGET RECONCILIATION ENGINE

Make reconciliation a first-class service.

Support:

```text
schema comparison
row count
column count
aggregate comparison
key coverage
min/max
null metrics
sum
distinct counts
partition comparison
hash
bucket hash
record comparison
transformation comparison
business-rule comparison
CDC comparison
incremental comparison
historical snapshot comparison
```

Example:

```text
SOURCE
Oracle.ERP.ORDERS

TARGET
Snowflake.MART.FACT_ORDERS

Mappings:
ORDER_NUMBER → ORDER_ID
CUSTOMER_NUMBER → CUSTOMER_ID
ORDER_TOTAL → QUANTITY * UNIT_PRICE - DISCOUNT
```

Store the mapping.

Generate source dialect SQL.

Generate target dialect SQL.

Execute both locally.

Compare small result sets.

---

# 25. HIERARCHICAL HASH RECONCILIATION

For massive tables:

```text
billions of rows
```

do not immediately perform record-level joins.

Implement architecture for:

```text
partition
   ↓
hash buckets
   ↓
mismatched bucket
   ↓
sub-buckets
   ↓
exception keys
   ↓
record comparison
```

Example:

```text
HASH(primary_key) % N
```

Compare:

```text
count
sum
hash
```

per bucket.

Drill only into mismatches.

Provide tests around deterministic hashing and canonical normalization.

Be aware that source/target systems may represent:

- null
- timestamp
- decimal
- string
- timezone
- floating point

differently.

Create canonical comparison normalization.

---

# 26. INCREMENTAL CERTIFICATION

Do not continuously rescan already-certified terabytes.

Persist:

```text
DQMetricHistory
CertificationBaseline
PartitionCertification
```

Track:

```text
dataset
partition
rule
metrics
hash
timestamp
status
rule_version
schema_version
code_version
```

If yesterday is certified and unaffected:

do not rerun it unnecessarily.

---

# 27. CHANGE INTELLIGENCE

When SQL/code changes:

```text
Git diff
   ↓
SQL AST diff
   ↓
affected columns
   ↓
column lineage
   ↓
affected rules
   ↓
affected downstream datasets
   ↓
selective recertification
```

Do not blindly rerun every quality rule.

Create interfaces to support this from the beginning.

---

# 28. COST INTELLIGENCE

Create a first-class Cost Intelligence subsystem.

Track both:

## Data execution cost

- estimated bytes scanned
- actual bytes scanned when available
- warehouse size
- query runtime
- query ID
- compute estimate
- query type
- cache usage if available

## AI cost

- model
- tokens in
- tokens out
- invocation purpose
- cached/not cached
- estimated cost
- agent
- run

Create:

```text
CostPolicy
CostEstimate
CostEvent
CostBudget
```

The execution planner should support limits such as:

```yaml
maximum_bytes_scanned: 100GB
require_partition_filter: true
allow_full_scan: false
maximum_exception_rows: 1000
timeout: 20m
```

A generated exploratory test must not be allowed to scan 80 TB automatically.

Planner should:

1. estimate,
2. optimize,
3. enforce policy,
4. require approval where needed.

---

# 29. QUERY OPTIMIZATION ENGINE

Implement an OptimizationPlanner abstraction.

It should evaluate:

- projection
- predicates
- partition pruning
- clustering/data skipping
- incremental windows
- cached baseline
- aggregate substitutes
- approximate strategies when permitted
- hash bucketing
- result limits
- exception limits
- concurrency
- warehouse-specific capabilities

Do not attempt to reinvent the warehouse optimizer.

Our job is to choose a sensible execution strategy.

Store:

```text
original plan
optimized plan
estimated scan
estimated cost
reason for optimization
```

---

# 30. WAREHOUSE-AWARE OPTIMIZATION

Adapters should expose platform-specific capability metadata.

Examples:

## Snowflake

Support concepts for:

- micro-partition pruning
- clustering
- warehouse size
- query history
- query profile
- caching

## BigQuery

- partitioning
- clustering
- dry-run cost estimate
- bytes processed
- projection optimization

## Databricks

- Delta
- data skipping
- partitions
- liquid clustering
- Photon
- statistics

## Redshift

- sort keys
- distribution
- WLM
- execution plan

Use this capability information in planning.

---

# 31. POLICY / SAFETY GATE

Never let agents freely change production.

Define remediation levels:

```text
LEVEL 0 Observe
LEVEL 1 Explain
LEVEL 2 Recommend
LEVEL 3 Generate Patch
LEVEL 4 Human-Approved Execution
LEVEL 5 Policy-Approved Autonomous Remediation
```

Default demo mode:

```text
Recommend / Generate Patch
```

Production code modification should require approval.

Airflow safe retry may later be policy-automated.

No destructive database operation may be autonomously executed.

---

# 32. REMEDIATION

Examples:

## dbt

- generate missing test
- generate SQL fix
- generate proposed model patch

## Airflow

- recommend retry
- recommend dependency change
- identify SLA/retry misconfiguration

## SQL

- generate proposed corrected transformation

Always capture:

```text
proposal
supporting evidence
affected objects
risk
approval requirement
```

---

# 33. IMPACT ANALYSIS

Failures must traverse downstream lineage.

Example:

```text
DIM_CUSTOMER
    ↓
FACT_SALES
    ↓
CUSTOMER_REVENUE
    ↓
EXECUTIVE_DASHBOARD
```

Return:

```text
affected datasets
affected models
affected pipelines
affected reports
affected business concepts
criticality
```

For demo, use known/registered consumers where necessary.

---

# 34. INCIDENT MANAGEMENT

Failed critical quality rules should be able to create incidents.

Canonical:

```text
Incident
Severity
Status
Dataset
Pipeline
FailedRule
EvidenceBundle
RootCauseClaim
Impact
Owner
Remediation
CertificationImpact
```

UI should provide a coherent investigation page.

---

# 35. QUALITY CERTIFICATION

A Data Product / Pipeline can be:

```text
CERTIFIED
AT_RISK
FAILED
UNKNOWN
```

Certification MUST be explainable.

No arbitrary AI-created quality score.

Score/status must derive from:

```text
rule status
severity
criticality
contract requirements
freshness
evidence
```

Display exactly why certification was granted or lost.

---

# 36. CLIENT DEMO SCENARIO — MUST WORK

Implement one exceptional end-to-end scenario.

Use:

# Revenue Quality Certification

Pipeline:

```text
SOURCE ORDERS
      ↓
Airflow
      ↓
RAW_ORDERS
      ↓
dbt staging
      ↓
dbt intermediate
      ↓
FACT_REVENUE
      ↓
Revenue Data Product
```

Business context:

```text
Net Revenue =
gross amount
- discount
- refund

Cancelled orders must not contribute revenue.

COMPLETE and SHIPPED orders are recognized.

Source and target revenue must reconcile.
```

Create a deliberately incorrect transformation such as:

```sql
WHERE status = 'COMPLETE'
```

when the approved contract requires:

```sql
WHERE status IN ('COMPLETE', 'SHIPPED')
```

Demo workflow:

### 1
User enters:

```text
Revenue
```

### 2
Context Intelligence identifies:

- business definition
- source
- target
- relevant columns
- transformation
- dbt model
- Airflow pipeline
- existing quality rules

### 3
AI generates candidate quality rules.

At minimum:

- schema
- completeness
- uniqueness
- referential integrity
- freshness
- volume
- gross revenue reconciliation
- net revenue reconciliation
- cancelled-order exclusion
- transformation formula
- source-target row coverage

### 4
User starts:

```text
Run Quality Certification
```

### 5
Real execution occurs:

- Airflow
- dbt
- SQL quality checks

### 6
Revenue reconciliation fails.

### 7
Evidence Intelligence collects:

- source metric
- target metric
- stage metrics
- dbt compiled SQL
- dbt result
- Airflow run/task state
- business contract
- lineage

### 8
RCA identifies:

```text
fact_revenue.sql excluded SHIPPED transactions
```

and links actual evidence.

### 9
Impact analysis displays affected data product.

### 10
Remediation Agent proposes:

```sql
WHERE status IN ('COMPLETE', 'SHIPPED')
```

### 11
Controlled approval applies fix.

### 12
Re-run.

### 13
All required rules pass.

### 14

```text
REVENUE DATA PRODUCT
CERTIFIED
```

This demonstration must be reproducible from documentation.

---

# 37. WHAT MUST BE REAL IN THE DEMO

These MUST be functional rather than static mocked UI:

- business context
- AI interpretation
- quality-rule generation
- deterministic SQL execution
- dbt execution
- Airflow execution
- source-target reconciliation
- evidence capture
- grounded RCA
- lineage
- remediation recommendation
- revalidation
- certification

Snowflake:

real if working credentials are available.

DuckDB:

must provide a fully working fallback.

---

# 38. WHAT MAY REMAIN ARCHITECTURAL / ADAPTER-CERTIFIED

Do NOT fake functionality.

These may be architecture/interfaces/tests rather than live infrastructure for the immediate demo:

- Kubernetes deployment
- Kafka
- production Temporal cluster
- Neo4j
- full enterprise SAML
- full multi-tenancy
- BigQuery live execution if credentials unavailable
- Redshift live execution if credentials unavailable
- Databricks live execution if credentials unavailable
- autonomous remediation
- advanced anomaly ML
- production Vault integration
- large-scale distributed cluster test

Clearly label status:

```text
IMPLEMENTED
INTEGRATION TESTED
CONTRACT TESTED
ARCHITECTED
NOT VERIFIED
```

Never report architecture as implementation.

---

# 39. FRONTEND PRODUCT EXPERIENCE

The UI must no longer feel like:

```text
dbt Projects
Airflow Projects
```

as the top-level product.

Use application navigation such as:

```text
Control Tower
Data Products
Pipelines
Quality
Business Context
Contracts
Lineage
Incidents
Evidence
Agents
Certifications
Cost
Administration
```

The main dashboard should answer:

```text
Are critical pipelines healthy?
Which data products are trusted?
What broke?
Which rules failed?
What changed?
What is affected?
What is the likely root cause?
What evidence supports it?
What should be fixed?
How much did testing cost?
```

UI principles:

- professional enterprise application
- high information density where appropriate
- clear hierarchy
- minimal decorative cards
- minimal gradients
- no excessive rounded containers
- no generic AI-purple design
- no random AI sparkle icons
- no fake activity feeds
- no meaningless scores
- no giant whitespace
- no marketing-style hero inside application pages
- no “AI slop”

Use:

- strong typography
- compact tables
- evidence drawers
- lineage graph
- investigation timeline
- cost visibility
- SQL inspection
- business/technical context side-by-side

The RCA page should be one of the strongest experiences.

---

# 40. ADMIN / OPERATIONS

Provide basic operational visibility:

```text
connections
adapter status
pipeline integration status
agent invocation count
AI cost
warehouse query cost
quality execution volume
failed runs
evidence volume
incidents
configuration
```

---

# 41. DATABASE DOMAIN MODEL

At minimum design models around:

```text
Organization
User
Project

Connection
DataPlatformConnection
PipelineConnection

BusinessDomain
BusinessConcept
BusinessDefinition
ContextSource
ContextObject
ContextRelationship

DataProduct
Dataset
Column
Transformation
Pipeline
PipelineTask

LineageNode
LineageEdge

QualityContract
QualityRule
RuleVersion
ExecutionPolicy

QualityRun
QualityRuleRun
Metric
ExceptionRecordReference

Evidence
EvidenceBundle
AgentClaim
ClaimEvidence

AgentRun

Incident
RootCauseAnalysis
ImpactAnalysis
RemediationProposal

Certification
CertificationRule

CostEvent
CostEstimate
CostPolicy

Artifact
AuditEvent
```

Use clean relational design.

Avoid duplicating the same concept per adapter.

---

# 42. API ARCHITECTURE

Design coherent endpoints around domain concepts, for example:

```text
/api/connections
/api/data-products
/api/datasets
/api/pipelines
/api/business-context
/api/contracts
/api/quality-rules
/api/quality-runs
/api/evidence
/api/incidents
/api/agents
/api/certifications
/api/costs
/api/lineage
```

Preserve backwards compatibility where practical.

Document changed/deprecated endpoints.

---

# 43. SECURITY

At minimum ensure:

- credentials not returned from API
- secrets redacted from logs
- safe query execution
- SELECT-only quality connections by default
- configurable statement timeout
- exception row limits
- no arbitrary shell execution from LLM-generated content
- agent tool allowlists
- remediation approval gates
- audit trail

Architect toward:

- OIDC
- SAML
- RBAC
- policy engine
- AWS Secrets Manager
- Azure Key Vault
- GCP Secret Manager
- Vault

Do not block client demo on full enterprise IAM.

---

# 44. TESTING REQUIREMENTS

Testing is not optional.

## Unit tests

Test:

- rules
- compilers
- adapters
- normalization
- context provenance
- evidence
- grounding
- cost policy
- optimization planner
- hashing
- reconciliation
- transformation AST analysis

## Contract tests

Each warehouse adapter must conform to the same interface.

Each pipeline adapter must conform to the same interface.

## Integration tests

Must include:

```text
DuckDB
dbt
Airflow
FastAPI
quality execution
evidence persistence
RCA path
```

## E2E tests

Automate client-demo path where practical:

```text
connect
→ discover
→ enter business context
→ generate rules
→ execute
→ fail
→ collect evidence
→ RCA
→ remediate
→ rerun
→ certify
```

## Negative tests

Test:

- missing context
- missing evidence
- contradictory evidence
- invalid SQL
- expensive query denied
- missing partition
- adapter failure
- Airflow failure
- dbt failure
- query timeout
- credentials failure
- agent malformed structured output

---

# 45. SCALE TESTING

Do not create actual multi-terabyte datasets locally.

Instead create deterministic synthetic performance fixtures that validate planning behavior.

Examples:

```text
estimated 10M rows
→ direct/native SQL strategy

estimated 300M rows
→ partition/aggregate strategy

estimated 3B rows
→ bucket hash strategy

estimated 20B rows
→ hierarchical reconciliation strategy

estimated 20TB scan
→ cost policy blocks full scan
→ planner proposes partitioned alternative
```

The planner must make expected decisions.

Do not falsely claim terabyte-scale physical execution was tested if it was not.

---

# 46. QUALITY OF IMPLEMENTATION

Do not add placeholder implementation such as:

```python
return {"status": "success"}
```

when the feature is represented as working.

Do not add:

- fake agents
- hardcoded RCA text
- fake evidence
- static lineage labeled dynamic
- fake warehouse results
- randomly generated quality scores
- fake costs
- placeholder production adapters presented as complete

Stubs are acceptable only when explicitly marked and covered by architecture/contract tests.

---

# 47. DOCUMENTATION DELIVERABLES

Create or update:

```text
README.md

docs/
  ARCHITECTURE.md
  PRODUCT_REQUIREMENTS.md
  TECH_STACK.md
  DATA_MODEL.md
  AGENT_ARCHITECTURE.md
  CONTEXT_INTELLIGENCE.md
  EVIDENCE_INTELLIGENCE.md
  GROUNDING_AND_ANTI_HALLUCINATION.md
  QUALITY_ENGINE.md
  QUALITY_RULE_TAXONOMY.md
  TRANSFORMATION_INTELLIGENCE.md
  RECONCILIATION_ENGINE.md
  EXECUTION_PLANNER.md
  SCALE_AND_PERFORMANCE.md
  COST_INTELLIGENCE.md
  OPTIMIZATION_ENGINE.md
  ADAPTER_ARCHITECTURE.md
  AIRFLOW_INTEGRATION.md
  DBT_INTEGRATION.md
  LINEAGE.md
  SECURITY.md
  OBSERVABILITY.md
  DEPLOYMENT_ARCHITECTURE.md
  CLIENT_DEMO_RUNBOOK.md
  TEST_STRATEGY.md
  ROADMAP.md
  IMPLEMENTATION_STATUS.md
  KNOWN_LIMITATIONS.md
```

Architecture docs must clearly distinguish:

```text
implemented now
tested now
architected next
future
```

---

# 48. ARCHITECTURE DECISION RECORDS

Create ADRs for important decisions:

```text
ADR-001 control-plane vs execution-plane
ADR-002 deterministic quality vs AI reasoning
ADR-003 context intelligence
ADR-004 evidence intelligence
ADR-005 quality rule abstraction
ADR-006 warehouse adapter model
ADR-007 pipeline adapter model
ADR-008 push-down execution
ADR-009 PostgreSQL migration
ADR-010 durable workflow / Temporal target
ADR-011 SQLGlot transformation parsing
ADR-012 cost-aware execution
ADR-013 claim/evidence grounding
ADR-014 remediation safety
```

---

# 49. TWO-HORIZON IMPLEMENTATION STRATEGY

We need both:

## Horizon A — Client Demonstration

Deliver a real vertical slice quickly.

Prioritize:

```text
Business context
→ transformation understanding
→ generated quality checks
→ dbt/Airflow execution
→ reconciliation
→ evidence
→ grounded RCA
→ remediation
→ re-test
→ certification
```

## Horizon B — Enterprise Architecture

The code must expose clean extension points for:

```text
PostgreSQL
Temporal
Kubernetes
Kafka
OpenLineage
Snowflake
BigQuery
Redshift
Databricks
customer execution plane
enterprise auth
policy engine
object storage
```

Do not compromise Horizon A by prematurely deploying every Horizon B component.

Do not compromise Horizon B with irreparable demo hacks.

---

# 50. IMPLEMENTATION PRIORITY

Follow roughly this order.

## Phase 0 — Audit

- inspect repository
- run current system
- capture baseline
- identify reusable components

## Phase 1 — Domain Model

Implement:

- business concepts
- contracts
- quality rules
- evidence
- claims
- incidents
- certification
- cost events

## Phase 2 — Adapter Abstraction

Refactor:

- dbt
- Airflow
- DuckDB/Snowflake

behind stable interfaces.

## Phase 3 — Quality Engine

Implement:

- canonical rules
- SQL generation
- deterministic execution
- result model

## Phase 4 — Context Intelligence

Implement:

- business context
- provenance
- structured resolver
- SQL/dbt/Airflow context enrichment

## Phase 5 — Transformation Intelligence

Implement SQLGlot analysis.

## Phase 6 — Evidence Intelligence

Implement:

- evidence normalization
- storage
- evidence bundles
- claim links

## Phase 7 — Agent Loop

Implement:

- context
- transformation
- quality
- evidence
- RCA

with structured outputs.

## Phase 8 — Grounding Gate

Enforce:

```text
no context → no action
no evidence → unverified
contradiction → conflict
```

## Phase 9 — Reconciliation

Implement:

- count
- aggregate
- hash
- key coverage
- row-level drill-down

## Phase 10 — Scale / Cost / Optimization

Implement planning abstractions and cost guardrails.

## Phase 11 — UI

Build serious control tower experience.

## Phase 12 — Demo

Build revenue scenario.

## Phase 13 — Certification

Run everything repeatedly.

---

# 51. DEFINITION OF DONE — DEMO

The demo is DONE only if a clean user session can:

1. Start application.
2. Access Control Tower.
3. Inspect Revenue Data Product.
4. See business context.
5. See source/target/pipeline/lineage.
6. Ask AI to generate quality coverage.
7. Inspect generated deterministic tests.
8. Run certification.
9. Trigger actual dbt execution.
10. Trigger actual Airflow execution.
11. Execute actual SQL quality checks.
12. Perform source-target reconciliation.
13. Produce a failure.
14. Persist real evidence.
15. Produce evidence-linked RCA.
16. Show impacted data product.
17. Generate remediation proposal.
18. Apply controlled demo remediation.
19. Rerun.
20. Pass required quality rules.
21. Show Certified status.
22. Display evidence trail.
23. Display generated/executed SQL.
24. Display cost/scan metrics where available.
25. Repeat successfully.

---

# 52. DEFINITION OF DONE — ARCHITECTURE

Architecture work is DONE only when:

- core boundaries exist in code,
- interfaces are typed,
- adapters are separable,
- agents cannot execute arbitrary tools,
- deterministic truth is separated from AI reasoning,
- provenance exists,
- evidence exists,
- claims link to evidence,
- cost policy exists,
- execution planner exists,
- warehouse-specific logic stays inside adapters/compilers,
- business context is versioned,
- rules are portable,
- implementation status is documented honestly.

---

# 53. COST-CONSCIOUS DEVELOPMENT INSTRUCTIONS

This project should also be economical to build and operate.

During implementation:

- reuse existing code,
- avoid unnecessary rewrites,
- avoid repeated repository-wide scans,
- do not create unnecessary subagents,
- run focused tests after focused changes,
- cache expensive interpretations,
- use deterministic parsers before LLM calls,
- use smaller/less-expensive model paths where capability permits,
- do not repeatedly regenerate artifacts that are unchanged.

At runtime:

- model-route by complexity,
- cache AI results,
- use SQLGlot before LLM SQL analysis,
- use metadata before data scans,
- use partitions before full scans,
- use aggregates before row comparison,
- use hashes before full reconciliation,
- reuse certified baselines,
- use lineage/change analysis to run only affected tests.

---

# 54. EXECUTION BEHAVIOR

Do not stop after producing a plan.

Continue implementation.

When you find an existing implementation:

prefer integrating/refactoring over duplicating it.

When a non-critical external integration is unavailable:

continue with another workstream.

Examples:

```text
No Snowflake credentials
→ finish DuckDB vertical slice and Snowflake contract tests.

No Kubernetes
→ continue local worker architecture.

No Temporal server
→ build workflow abstraction and retain local executor temporarily.

No BigQuery credentials
→ implement adapter contract and compiler tests.
```

One unavailable service must not block the entire product.

---

# 55. DO NOT CLAIM SUCCESS EARLY

Do not say:

```text
implemented end-to-end
```

unless it actually is.

At completion provide a matrix:

| Capability | Implemented | Unit Tested | Integration Tested | E2E Tested | Live External Tested |
|---|---|---|---|---|---|

Include:

- Context Intelligence
- Evidence Intelligence
- Grounding
- Quality Engine
- Reconciliation
- Cost Intelligence
- Optimization
- DuckDB
- Snowflake
- BigQuery
- Redshift
- Databricks
- dbt Core
- dbt Cloud
- Airflow
- RCA
- Remediation
- Certification
- UI

No inflated claims.

---

# 56. FINAL VALIDATION

Before considering work complete run:

```text
backend lint
backend type checks where configured
backend unit tests
frontend lint
frontend type check
frontend build
adapter contract tests
integration tests
E2E tests
security/basic secret scan
demo run
```

Fix failures.

Do not merely document them unless they require unavailable external credentials/infrastructure.

---

# 57. FINAL REPORT

When finished provide:

## A. Executive summary

What is now operational.

## B. Architecture

What changed.

## C. Working end-to-end flow

Exact demonstrated flow.

## D. Tests

Commands and results.

## E. Adapter certification

Per-adapter status.

## F. AI grounding

How hallucination is prevented.

## G. Scale

How billion-row/TB-scale workloads are handled.

## H. Cost

AI + warehouse cost controls.

## I. Known limitations

Precise and honest.

## J. Next phase

Prioritized enterprise implementation.

## K. Demo instructions

Exact steps to reproduce client demonstration.

---

# 58. ARCHITECTURAL PRINCIPLES TO PROTECT

Treat these as invariants:

### Principle 1

> **No agent action without context.**

### Principle 2

> **No material agent conclusion without evidence.**

### Principle 3

> **No production-changing action without policy.**

### Principle 4

> **AI defines quality intent; deterministic engines determine truth.**

### Principle 5

> **Move computation to the data, not terabytes of data to the accelerator.**

### Principle 6

> **Every result must be explainable and reproducible.**

### Principle 7

> **Cost is part of execution planning, not an afterthought.**

### Principle 8

> **Business context and technical lineage belong in the same reasoning system.**

### Principle 9

> **Warehouse and orchestrator integrations are adapters, not product architecture.**

### Principle 10

> **Never fake implementation status for a client demo.**

---

# 59. PRODUCT QUALITY BAR

This is intended to become an enterprise accelerator used for serious data estates.

Treat it accordingly.

The final product should feel closer to:

```text
enterprise data reliability platform
+
pipeline assurance platform
+
business-aware quality control plane
+
agentic investigation system
```

than to:

```text
chatbot
+
some SQL
+
dashboard cards
```

The differentiating product capabilities are:

```text
Business Context Intelligence
Evidence Intelligence
Grounded AI
Transformation Intelligence
Automated Quality Contract Generation
Source-to-Target Reconciliation
Pipeline Correctness Testing
Scale-Aware Execution Planning
Cost Intelligence
Change-Aware Testing
Evidence-Grounded Root Cause Analysis
Impact Analysis
Controlled Remediation
Continuous Data Product Certification
```

Those capabilities must drive architecture, implementation and user experience.

Begin by auditing the current repository and verifying the existing working baseline.

Then implement continuously toward the complete end-to-end vertical slice.

Do not stop at planning.