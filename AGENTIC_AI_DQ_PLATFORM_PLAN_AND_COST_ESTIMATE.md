# Agentic AI Data Quality & Pipeline Assurance Platform
## Implementation Plan & Cost Estimate

**Prepared from:** `AGENTIC_AI_DATA_QUALITY_TECHNICAL_ARCHITECTURE_V2.md`, `MASTER IMPLEMENTATION PROMPT — AGENTIC AI DATA QUALITY & PIPELINE ASSURANCE PLATFORM.md`
**Baseline:** ADE Test Control Tower v0.2 (existing, working — real dbt-core execution, isolated per-project venvs, real per-project Airflow instances, dbt Cloud API foundation, lineage capture, multi-job/multi-DAG orchestration)
**Rate basis:** US-based senior delivery team (per your selection)
**Estimate class:** ROM (Rough Order of Magnitude), ±35% — refine after Phase 0 discovery and vendor/credential confirmation

---

## 1. What's being estimated

The source documents describe two things that need to be estimated separately, because they are different investments with different payback:

- **Horizon A — Real vertical slice ("Two-Day Demo Architecture" in the spec).** Evolves the *existing, working* v0.2 tool with the minimum real (not mocked) capability to run the "Revenue Quality Certification" scenario end to end: business contract → AI-generated checks → real dbt/Airflow execution → source-to-target reconciliation → a real failure → evidence-grounded RCA → remediation proposal → re-test → certification. This is the credible client demonstration.
- **Horizon B — Full enterprise target architecture.** Everything in the 61-section technical architecture spec: PostgreSQL/pgvector, Temporal, full agent supervisor (10+ agents), LLM gateway, 4 warehouse adapters + 3 pipeline adapters at production grade, cost/scale/optimization engines, Next.js control tower, security/SSO, Kubernetes/Helm/Terraform across AWS/Azure/GCP/private-VPC, observability stack, OpenLineage.

Building Horizon A does not throw away work — it *is* the first slice of Horizon B, built on the same domain model, just without the enterprise infrastructure (Postgres, Temporal, K8s, full agent roster) wired in yet. This is why the estimate is phased rather than a single number.

---

## 2. Team & rate assumptions (US-based senior team)

| Role | Rate/hr | Basis |
|---|---|---|
| Principal/Staff Architect | $225 | Owns domain model, adapter contracts, grounding architecture |
| Senior Backend Engineer (Python/FastAPI) | $185 | Control plane, APIs, quality rule engine |
| Senior AI/Agent Engineer | $195 | LLM gateway, agent supervisor, grounding gateway, RCA |
| Senior Data Engineer (dbt/Airflow/warehouses) | $180 | Adapters, reconciliation engine, lineage |
| Senior Frontend Engineer (Next.js/React) | $175 | Control tower UI, investigation UX |
| DevOps/Platform Engineer | $180 | Docker/K8s/Terraform/Temporal/observability |
| QA/Test Engineer | $145 | Unit/contract/integration/E2E/negative tests |
| Security Engineer (fractional) | $200 | Auth, secrets, query safety, policy |
| Technical Product Manager | $165 | Scope, client demo choreography, roadmap |
| UX Designer (fractional) | $155 | Enterprise information architecture, design system |

1 FTE-month ≈ 173 hours. All costs below are labor only unless marked; infra/tooling/LLM API spend is called out separately per horizon.

---

## 3. Horizon A — Real Vertical Slice

**Duration:** 8 weeks (2 months) | **Goal:** everything in Master Prompt §36 ("Client Demo Scenario") and §51 ("Definition of Done — Demo") works for real against the existing v0.2 foundation.

### 3.1 Scope (maps to Master Prompt Phases 0–9, demo-scoped)

| Workstream | What gets built | Reuses from v0.2 |
|---|---|---|
| Phase 0 — Audit | `CURRENT_STATE.md`: what's real vs. partial vs. needs replacement | — |
| Phase 1 — Domain model (slice) | `BusinessConcept`, `QualityContract`, `QualityRule`, `Evidence`, `AgentClaim`, `Incident`, `Certification` tables (SQLAlchemy, SQLite for now, Postgres-compatible schema) | Extends existing `DbtProject`/`AirflowProject`/`TestRun` models |
| Phase 2 — Adapter abstraction (slice) | `DataPlatformAdapter`/`PipelineAdapter` ABCs; DuckDB adapter fully implemented; existing dbt-core/Airflow/dbt-Cloud code refactored behind `PipelineAdapter` | `dbt_runner.py`, `airflow_client.py`, `dbt_cloud_client.py` become adapter implementations, not rewrites |
| Phase 3 — Quality Rule Engine (slice) | Canonical `QualityRule` model; SQLGlot-based rule compiler for DuckDB dialect; dbt-test compiler backend | New |
| Phase 4 — Context Intelligence (slice) | Structured `ContextPackage` resolver: business contract + dbt manifest + Airflow DAG metadata → one grounded package (no vector DB yet — structured + code retrieval only) | Existing `lineage.py` feeds this |
| Phase 5 — Transformation Intelligence | SQLGlot analyzer: SQL → inputs/outputs/CASE/JOIN/FILTER/GROUP BY structure | New |
| Phase 6 — Evidence Intelligence (slice) | `Evidence`/`EvidenceBundle` persistence; warehouse + dbt + Airflow evidence normalized into one shape | Extends existing `Artifact`/`DbtTestResult`/`AirflowTaskResult` |
| Phase 7 — Agent loop (5 agents) | Context Agent, Transformation Agent, Quality Agent, Evidence Agent, RCA Agent — typed Pydantic I/O, one LLM gateway (single provider for the slice) | New |
| Phase 8 — Grounding Gateway | `AgentClaim` + status machine (SUPPORTED/UNVERIFIED/CONFLICTED); hard block on missing context | New |
| Phase 9 — Reconciliation (slice) | Row count, aggregate, key coverage, hash reconciliation between source and target (DuckDB↔DuckDB for the demo; Snowflake↔DuckDB if credentials are provided) | New |
| Demo scenario | "Revenue Quality Certification" reference pipeline + injected defect + full replay script | New |
| UI (incremental, not full Next.js) | Evolve the existing static UI: add Contracts, Quality Runs, Evidence drawer, RCA view, Certification badge to the current project-detail pages | Extends current vanilla JS UI |
| Testing | Unit (rule model, compiler, grounding, reconciliation, transformation parsing), adapter contract tests, one E2E replay of the demo scenario | New |

### 3.2 Team (average allocation over 8 weeks)

| Role | FTE | Person-months | Hours | Cost |
|---|---:|---:|---:|---:|
| Principal Architect | 0.5 | 1.0 | 173 | $38,925 |
| Senior Backend Engineer ×2 | 2.0 | 4.0 | 692 | $128,020 |
| Senior AI/Agent Engineer | 1.0 | 2.0 | 346 | $67,470 |
| Senior Data Engineer | 1.0 | 2.0 | 346 | $62,280 |
| Frontend Engineer | 0.5 | 1.0 | 173 | $30,275 |
| QA Engineer | 0.5 | 1.0 | 173 | $25,085 |
| Technical PM | 0.25 | 0.5 | 87 | $14,272 |
| **Total** | **5.75** | **11.5** | **1,990** | **≈ $366,000** |

### 3.3 Horizon A infra/tooling (not labor)

| Item | Est. cost (2 months) |
|---|---:|
| LLM API spend (dev + demo runs, single provider) | $2,000–$5,000 |
| Cloud dev/staging compute (small — this still runs on local/single-VM Docker per the spec's "standalone Docker" mode) | $1,000–$2,000 |
| Snowflake trial/dev credits (optional, only if live Snowflake demo requested) | $1,000–$3,000 |
| **Subtotal** | **≈ $5,000–$10,000** |

### 3.4 Horizon A total: **≈ $370,000–$380,000, 8 weeks**

---

## 4. Horizon B — Full Enterprise Target Architecture

**Duration:** 12 months (parallel workstreams after month 2, once Horizon A's domain model exists) | **Goal:** everything in the 61-section technical architecture spec, including deployment portability (§43) across Docker/Kubernetes/cloud-VPC.

### 4.1 Scope (maps to Master Prompt Phases 2–13, full enterprise depth)

| Workstream | Key deliverables |
|---|---|
| Full adapter layer | Production-grade Snowflake, BigQuery, Redshift, Databricks adapters (contract-tested; live-tested only where credentials exist); MWAA/Composer/Astronomer pipeline adapters |
| Full agent architecture | Remaining agents (Metadata, Business Context, Lineage, Mapping, Impact, Remediation) + Agent Supervisor; multi-provider LLM Gateway with routing, caching, cost accounting |
| Quality Execution Planner | Scale Intelligence, Cost Intelligence, Change Intelligence, Optimization Engine — full cost-gated, warehouse-aware planning |
| Reconciliation at scale | Hierarchical hash/bucket reconciliation for billion-row tables; canonical value normalization (NULL/decimal/timestamp/tz) |
| Incremental certification | `DQMetricHistory`, `CertificationBaseline`, `PartitionCertification`; change-aware selective re-certification from Git diff → column lineage → impacted rules |
| Storage migration | PostgreSQL + pgvector (replacing SQLite), S3-compatible object storage, Redis cache |
| Durable workflow | Temporal replacing asyncio orchestration, with human-approval waits and crash recovery |
| Enterprise frontend | Full Next.js/React/TypeScript rebuild: Control Tower, Data Products, Pipelines, Quality, Business Context, Contracts, Lineage, Incidents, Evidence, Agents, Certifications, Cost, Administration |
| Security & identity | OIDC/SAML SSO, RBAC, secrets abstraction (Vault/cloud secret managers), agent tool allowlists, audit trail |
| Deployment portability | Docker Compose, Kubernetes (Helm + overlays, cloud-neutral), Terraform modules per cloud, OCI image pipeline, control-plane/execution-plane split for customer-VPC execution |
| Observability | OpenTelemetry, Prometheus, Grafana, Sentry, core metrics dashboard |
| OpenLineage | Lineage model migrated to OpenLineage-compatible entities/events |
| Testing at scale | Full adapter contract suite, integration suite, E2E suite, negative-path suite, synthetic scale-planning tests (10M→PB-scale planner decisions, not physical TB benchmarks) |
| Documentation & ADRs | Full `docs/` set from Master Prompt §47, plus ADR-001…014 from §48 |

### 4.2 Team (average allocation over 12 months — ramps up from Horizon A's team, peaks mid-build, tapers for hardening)

| Role | Avg FTE | Person-months | Hours | Cost |
|---|---:|---:|---:|---:|
| Principal Architect | 1.0 | 12.0 | 2,076 | $467,100 |
| Senior Backend Engineer | 2.5 | 30.0 | 5,190 | $960,150 |
| Senior AI/Agent Engineer | 1.5 | 18.0 | 3,114 | $607,230 |
| Senior Data Engineer | 2.0 | 24.0 | 4,152 | $747,360 |
| Senior Frontend Engineer | 1.5 | 18.0 | 3,114 | $544,950 |
| DevOps/Platform Engineer | 1.0 | 12.0 | 2,076 | $373,680 |
| QA/Test Engineer | 1.0 | 12.0 | 2,076 | $301,020 |
| Security Engineer (fractional) | 0.4 | 4.8 | 830 | $166,080 |
| Technical PM | 0.75 | 9.0 | 1,557 | $256,905 |
| UX Designer (fractional) | 0.35 | 4.2 | 727 | $112,623 |
| **Total** | **~12.0** | **144** | **~24,900** | **≈ $4,537,000** |

### 4.3 Horizon B infra/tooling/third-party (not labor, 12 months)

| Item | Est. cost |
|---|---:|
| LLM API spend (multi-agent, higher volume, dev+staging+demo) | $60,000–$120,000 |
| Cloud infra — dev/staging/prod-like K8s clusters across environments | $150,000–$250,000 |
| Temporal (self-hosted infra or Temporal Cloud) | $20,000–$60,000 |
| Snowflake / BigQuery / Redshift / Databricks dev+test capacity | $60,000–$120,000 |
| Observability stack (Grafana Cloud/Sentry/hosting) | $15,000–$30,000 |
| Security review / penetration test (pre-GA) | $40,000–$80,000 |
| Misc. licenses/tools | $15,000–$30,000 |
| **Subtotal** | **≈ $360,000–$690,000** (use $500,000 as point estimate) |

### 4.4 Contingency

12% on labor + infra, standard for a program of this novelty (agentic architecture, multi-cloud portability, several first-time integrations): **≈ $605,000**

### 4.5 Horizon B total: **≈ $5.6M–$5.7M, 12 months**

---

## 5. Combined program total

| | Duration | Labor | Infra/Tooling | Contingency | Total |
|---|---:|---:|---:|---:|---:|
| Horizon A | 2 months | $366,000 | $7,500 | included above | **≈ $375,000** |
| Horizon B | 12 months | $4,537,000 | $500,000 | $605,000 | **≈ $5,642,000** |
| **Combined** | **~14 months** | **$4,903,000** | **$507,500** | **$605,000** | **≈ $6.0–6.1M** |

**This is a ROM estimate**, not a fixed-price quote. The single biggest levers on the final number, in order:

1. **Team sourcing mix.** This uses 100% US-based senior rates per your instruction. A blended onshore/offshore delivery model (common for a UST engagement) typically brings Horizon B labor down 35–50%, i.e., toward $2.3M–$3.0M for the same scope — ask if you want that variant run side by side.
2. **How many of the four warehouse adapters get *live* credentials during the build.** Contract-tested-only (per Master Prompt §38, explicitly allowed) is materially cheaper than live-testing all four.
3. **Whether Horizon B genuinely needs all three deployment targets (Docker/K8s/cloud-VPC) in year one**, or whether Kubernetes/multi-cloud can be deferred to a post-GA phase — this alone is roughly 1.5-2 FTE-years of DevOps/security work.
4. **LLM cost regime** (model choice, caching discipline) — the plan already assumes aggressive cost-routing per Master Prompt §21/§53, but actual agent call volume in production will move this number.

---

## 6. Recommended sequencing

1. **Weeks 1–2:** Phase 0 audit (already substantially done — v0.2's `docs/ARCHITECTURE.md`/`docs/RUNBOOK.md` cover most of this) + finalize Horizon A scope sign-off.
2. **Weeks 3–8:** Build Horizon A vertical slice (this document's §3), demo the Revenue Quality Certification scenario live.
3. **Decision gate:** Use the Horizon A demo to secure funding/commitment for Horizon B before staffing up to 12 FTEs.
4. **Months 3–14:** Horizon B, phased per Master Prompt §50, with quarterly checkpoints re-costing against actuals (LLM spend and cloud spend are the two line items most likely to move).

---

## 7. What I'm doing next

Per the master prompt's own instruction ("do not stop at planning — continue implementation"), I'm proceeding to start Horizon A implementation now: Phase 0 audit doc, then the domain model extension (Phase 1) on top of the existing v0.2 platform. I'll report progress against the capability matrix (Implemented / Unit Tested / Integration Tested / E2E Tested / Live External Tested) as it's built — no capability will be reported as done unless it's real, per the same document's explicit prohibition on inflated claims.
