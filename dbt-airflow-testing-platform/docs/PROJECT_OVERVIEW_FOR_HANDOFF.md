# Project Overview — Handoff Brief

Written as one architect handing this to another (or to a different AI
coding agent) cold. No optimism, no hedging. If a claim below isn't backed
by a passing test or a live-verified run, it's labeled as such.

---

## 1. The idea

Client gave three docs (in `~/Downloads/`, not in this repo):
`AGENTIC_AI_DATA_QUALITY_TECHNICAL_ARCHITECTURE_V2.md`, its near-duplicate
`_ARCHITECTURE.md`, and `MASTER IMPLEMENTATION PROMPT...md`. They describe
a target product: an **Agentic AI Data Quality & Pipeline Assurance
Platform** — not a test runner, a "business-aware, evidence-grounded data
reliability control plane." Core loop the spec wants:

```
business intent → context → quality contract → AI proposes checks
→ deterministic execution → reconciliation → evidence → failure detected
→ evidence-grounded RCA → impact analysis → remediation → re-test → certify
```

Non-negotiable rule stated repeatedly in the spec: **AI decides WHAT to
test; deterministic engines prove WHETHER it passed.** Agents propose,
never assert truth on their own say-so.

Existing foundation before any of this: **ADE Test Control Tower v0.1/v0.2**
— a working tool (built earlier in this same engagement) that provisions
real per-project dbt-core venvs and real per-project Airflow instances, runs
real jobs/DAGs, captures real lineage. That's the substrate everything below
sits on. It was preserved, not thrown away.

## 2. Implementation plan (as actually proposed and executed against)

I split this into two horizons and gave a written cost estimate
(`~/Downloads/AGENTIC_AI_DQ_PLATFORM_PLAN_AND_COST_ESTIMATE.md` +
matching PPT):

- **Horizon A** — a real, small vertical slice on top of v0.2. Estimated
  ~$370-380K, 8 weeks, ~6 FTE. This is what's actually been built (v0.3
  through v0.6 below).
- **Horizon B** — the full spec: PostgreSQL/pgvector, Temporal, Kafka,
  Next.js/React/TypeScript enterprise UI, all four warehouse adapters
  production-grade, full ~11-agent roster, cost/scale/optimization
  engines, Kubernetes/Terraform/multi-cloud, OIDC/SAML, OpenTelemetry.
  Estimated ~$5.6-5.7M, 12 months, ~12 FTE average. **Zero of this has
  been started.** It exists only as the estimate document and the
  client's own spec. This was a deliberate scope decision, stated up
  front, not a silent gap.

Sequencing choice inside Horizon A: build the deterministic substrate
(rules, evidence, certification, grounding) *before* any LLM agent, because
the spec's own rule ("no agent action without context/evidence") makes an
agent built before that substrate exists meaningless — it would have
nothing real to ground claims in. That choice is why the "AI" part of
"Agentic AI" arrived late and is still thin (see §5).

## 3. What's implemented and verified (not just written)

Tagged commits, in order, each independently tagged in git:

| Tag | What it added |
|---|---|
| v0.1.0 | Single dbt+Airflow project MVP. Real dbt-core execution in an isolated venv, real per-project Airflow instance (webserver+scheduler+triggerer), three real macOS fork-safety bugs found and fixed. |
| v0.2.0 | Multi-project platform: any number of dbt/Airflow projects, each independently provisioned, lineage capture, multi-job/DAG orchestration. |
| v0.3.0-horizon-a | Domain model (`BusinessConcept`, `QualityContract`, `QualityRule`, `Evidence`, `AgentClaim`, `Incident`, `Certification`). Adapter SDK ABCs (`DataPlatformAdapter`/`PipelineAdapter`) — **only DuckDB has a real implementation**; Snowflake/BigQuery/Redshift/Databricks are undefined beyond a config field. Quality Rule Engine: canonical rule model, SQLGlot-based dialect compiler, 6 rule types, executed for real against a real DuckDB warehouse. |
| v0.4.0-horizon-a | Grounding Gateway (`services/grounding.py`, deterministic status machine — not an LLM call). Deterministic RCA (`services/rca.py`, walks real captured lineage to the one failing upstream dataset). Remediation (`services/remediation.py`: propose → human-approve → apply, a scoped, unique-match file patch). **The full "Revenue Quality Certification" demo scenario from the spec**, built as a real dbt project (`revenue_demo/`) with the exact injected defect, fully scripted and asserted end to end (`scripts/run_revenue_demo.py`): real fail → real evidence → real FAILED certification → real RCA claim → real approved-and-applied fix → real rebuild → real CERTIFIED. Found and fixed a real cross-project data bug along the way (certification/RCA weren't scoping by `dbt_project_id`). |
| v0.5.0-horizon-a | Browser UI extended to cover all of the above (Quality Rules, Certifications, Investigate/RCA modal, Remediation propose/approve/apply, Incidents nav) — through v0.4 this was API/script-only. |
| v0.6.0-horizon-a | LLM Gateway (`services/llm_gateway.py`, provider-neutral ABC + OpenAI implementation) and the **first real agent**, `services/rca_agent.py`. |

**Test suite**: 40 pytest tests, all passing, plus one full live end-to-end
script run and multiple direct live API checks (documented with actual
output in `docs/IMPLEMENTATION_STATUS.md`). Nothing in the table above is
"implemented" without a corresponding test or a live-verified run — where
that's not true, it's flagged in §5.

## 4. What's completed vs. pending vs. not started

**Completed and verified real:**
- Real dbt-core + real Airflow execution, multi-project (v0.1-v0.2)
- Real DuckDB-backed Quality Rule Engine (6 rule types, SQLGlot compiler)
- Real deterministic Grounding Gateway + RCA (lineage-walk based)
- Real controlled remediation loop (propose/approve/apply with safety checks)
- Real end-to-end demo scenario matching the spec's own reference scenario
- A working (if plain) browser UI covering all of the above

**Pending (designed/scaffolded, not finished):**
- **The RCA agent has never made a real LLM call.** I asked which provider
  (you said OpenAI) and to add `OPENAI_API_KEY` to `backend/.env`. That key
  was never added. The agent is real code with 6 passing tests against a
  *fake* gateway and one live-verified graceful-degradation run (correctly
  returns `UNVERIFIED` with no key, doesn't crash, doesn't guess) — but zero
  tokens have ever been spent against a real OpenAI endpoint. This is the
  single biggest reason "Agentic AI" is still mostly deterministic code.
- Evidence Intelligence bundling / Tier 1-5 provenance ranking — the
  `Evidence`/`ClaimEvidenceLink` tables exist, no bundling, no tiering.

**Not started at all:**
- Transformation Intelligence (SQLGlot AST analysis of dbt model SQL to
  *suggest* rules — distinct from the rule-SQL compiler that already exists)
- 10 of the spec's ~11 named agents (Metadata, Business Context, Lineage,
  Transformation, Mapping, Quality/test-generation, Execution Planning,
  Evidence, Impact, Remediation-generation) — only RCA exists, and even
  that hasn't made a real model call yet
- Context Intelligence (structured/semantic/graph retrieval across
  glossary, Git, live systems)
- Reconciliation beyond row-count/aggregate: hash/bucket, key coverage
- Cost/Scale/Optimization/Change Intelligence — none of it
- Snowflake/BigQuery/Redshift/Databricks adapters (Snowflake has a
  `profiles.yml` template and nothing else)
- All of Horizon B: PostgreSQL, pgvector, Temporal, Kafka, object storage,
  Redis, the entire Next.js/React/TypeScript UI, Kubernetes/Helm/Terraform,
  OIDC/SAML/RBAC, OpenTelemetry/Prometheus/Grafana/Sentry, multi-tenancy,
  policy engine (OPA), secrets manager integration
- Project deletion (dbt/Airflow project rows and on-disk venvs just
  accumulate — no cleanup UI or endpoint)

## 5. The UI — is it AI slop?

The spec (Master Prompt §39, Architecture spec §48) explicitly bans:
excessive cards, decorative gradients, meaningless AI scores, purple
AI-styling, fake activity streams, sparkle icons, marketing hero panels.
And explicitly wants: dense enterprise tables, evidence drawers,
investigation workflows, a serious data-platform feel, built in
Next.js/React/TypeScript/Radix/TanStack/React Flow/ECharts.

What actually exists: a single-file-per-concern **vanilla HTML/JS SPA**,
hash-routed, styled with Tailwind pulled from a CDN (no build step, no
design system, no component library), dark theme, plain `<table>` markup,
a hand-rolled SVG renderer for the lineage graph, browser `alert()` for some
error paths, and a raw JSON textarea for entering a rule's `expression`
field (i.e., a data-quality "business rule" sometimes requires typing
`{"sql": "SELECT ..."}` by hand).

Honest answer: **it is not slop in the specific ways the spec warns
against** — no gradients, no fake scores, no sparkles, no marketing
chrome; I was deliberate about avoiding those. But it is also **not** the
"serious enterprise data platform" the spec asks for. It's a functional
internal engineering console — fine for verifying that the backend works,
not something you'd put in front of the "business user" persona the spec
describes, and not built on the tech stack the spec names. If judged
against the spec's own bar, it's a fail on ambition even though it isn't a
fail on the specific anti-patterns called out.

## 6. Why the job isn't complete

Plainly, in order of weight:

1. **Scale mismatch.** My own cost estimate for the full spec is ~$6M,
   ~14 months, ~12 FTE average. What exists is one agent, one continuous
   session, building the smallest real vertical slice I could scope
   (Horizon A). The gap between "the spec" and "what's built" is not a
   surprise — it's the exact gap the two-horizon plan named on day one.
2. **The one external dependency I explicitly asked for was never
   provided.** An LLM API key. Every remaining "agent" in the spec —
   Quality/test-generation, Transformation, Impact, Mapping, a
   fully-LLM-capable RCA — needs the same `LLMGateway` this session built,
   and none of them can be *real* (as opposed to a stub returning canned
   text, which the spec explicitly forbids) without a working key. This
   single missing credential is the actual blocker on every remaining
   agent, not a capability gap in what's been built.
3. **Sequencing.** I chose to build the deterministic substrate
   (rules/evidence/grounding/certification) before any agent, per the
   spec's own "no agent action without evidence" rule. Correct, but it
   means the visibly-"agentic" surface area is thin relative to how much
   backend work has actually happened.
4. **Horizon B was scoped out on purpose**, not abandoned mid-build — it
   was never started because the plan said not to start it without a
   funding/commitment decision after seeing Horizon A work.

None of that is a claim that everything remaining is easy or that a
different session would trivially finish it — the honest capability matrix
in `docs/IMPLEMENTATION_STATUS.md` says exactly what's real vs. not, and
that document is more trustworthy than any summary paragraph, including
this one.
