# Implementation Status — Horizon A (in progress)

Honest status against the capability matrix requested by the master
implementation prompt (§55). No capability below is marked done unless it
is real: live-executed, not mocked, not a `return {"status": "success"}`
stub.

| Capability | Implemented | Unit Tested | Integration Tested | E2E Tested | Live External Tested |
|---|:---:|:---:|:---:|:---:|:---:|
| Domain model (contracts/rules/evidence/claims/incidents/certification) | ✅ | — | ✅ | ✅ | — |
| Adapter SDK (`DataPlatformAdapter`/`PipelineAdapter` ABCs) | ✅ | — | — | — | — |
| DuckDB adapter | ✅ | ✅ | ✅ | ✅ | ✅ (real warehouse file) |
| Snowflake/BigQuery/Redshift/Databricks adapters | ❌ | — | — | — | — |
| Quality Rule Engine (canonical rule + SQLGlot compiler) | ✅ | ✅ | ✅ | ✅ | — |
| Rule types: not_null, unique, accepted_values, row_count_reconciliation, aggregate_reconciliation, custom_sql | ✅ | ✅ | ✅ | ✅ | — |
| Evidence persistence | ✅ | — | ✅ | ✅ | — |
| Certification (derived, explainable, no AI score) | ✅ | ✅ | ✅ | ✅ | — |
| Incident auto-creation on P1 failure | ✅ | — | ✅ | ✅ | — |
| **Claim/Evidence Grounding Gateway** (deterministic status machine, not an LLM call — see below) | ✅ | ✅ | ✅ | ✅ | — |
| **Evidence-grounded RCA** (deterministic lineage walk to localize a failure upstream) | ✅ | ✅ | ✅ | ✅ | — |
| **Controlled remediation** (propose → human-approve → apply, scoped find/replace) | ✅ | — | ✅ | ✅ | — |
| **Revenue Quality Certification demo scenario** (`revenue_demo/`, `scripts/run_revenue_demo.py`) | ✅ | — | — | ✅ | — |
| **Browser UI** for rules/certification/RCA/remediation (was API/script-only through v0.4) | ✅ | — | — | ✅ (manually, in-browser) | — |
| Context Intelligence | ❌ | — | — | — | — |
| Transformation Intelligence (SQLGlot AST analysis of *dbt SQL*, distinct from rule-SQL compilation above) | ❌ | — | — | — | — |
| Evidence Intelligence bundling / Tier 1-5 provenance ranking | ⚠️ partial (typed `Evidence` rows + a claim/evidence link exist; no bundles, no tier field yet) | — | — | — | — |
| **LLM Gateway** (`services/llm_gateway.py`, provider-neutral ABC + OpenAI implementation) | ✅ | ✅ (fake gateway) | — | — | ❌ (no API key configured yet) |
| **RCA Agent, first real agent** (`services/rca_agent.py` — escalated to only when the deterministic walk finds >1 upstream failure at once; picks from a whitelisted candidate set, cites evidence IDs verified against a whitelist, status computed by Grounding Gateway from verified links, not the LLM's own confidence) | ✅ | ✅ (6 tests, fake gateway — see below) | ✅ (live via real API with no key configured → graceful UNVERIFIED, not a crash) | ✅ | ❌ (no OpenAI key configured yet — see below) |
| AI cost accounting (`LLMCallLog`: provider/model/tokens in+out per call) | ✅ | ✅ | — | — | — |
| Other agents (Metadata, Business Context, Lineage, Transformation, Mapping, Quality/test-generation, Execution Planning, Evidence, Impact, Remediation) | ❌ | — | — | — | — |
| Reconciliation: hash/bucket, key coverage | ❌ (row count + aggregate reconciliation only) | — | — | — | — |
| Cost/Scale/Optimization/Change Intelligence | ❌ | — | — | — | — |
| dbt-core execution (v0.2, carried forward) | ✅ | — | ✅ | ✅ | ✅ |
| dbt Cloud execution (v0.2, carried forward) | ✅ | — | — | — | ❌ (no credentials) |
| Airflow execution (v0.2, carried forward) | ✅ | — | ✅ | ✅ | ✅ |
| PostgreSQL / Temporal / K8s / Next.js UI | ❌ (Horizon B) | — | — | — | — |

## Why Grounding is deterministic, and why an LLM agent exists now

The Architecture spec's own grounding rules (§11.3) are a plain status
machine over evidence counts (missing context → BLOCK, no evidence →
UNVERIFIED, contradictory evidence → CONFLICTED, reproducible evidence →
SUPPORTED) — that's `services/grounding.py`, and it's deterministic code, not
a model call, and stays that way regardless of whether an LLM is involved
upstream of it.

Through v0.4, RCA was *entirely* deterministic: `services/rca.py` walked the
project's captured dbt lineage graph to the first upstream dataset with a
failing certification. That's genuinely sufficient when exactly one upstream
dataset is failing — there's nothing for an LLM to add. It stops being
sufficient when *more than one* upstream dataset fails at the same time: a
lineage walk has no basis to rank them, and picking "the first one found" in
that case would be exactly the kind of unsupported guess the spec prohibits.

`services/rca_agent.py` (new) is the actual first AI agent in this codebase
— it's invoked *only* from that ambiguous branch. It does not get to assert
a claim's status: it picks one candidate from a fixed whitelist (the
datasets `rca.py` already found failing) and cites evidence IDs from a fixed
whitelist (the evidence those failures actually produced); both are verified
against the whitelist before anything is persisted — an unlisted dataset
name or a fabricated evidence ID is discarded, not trusted. The claim's
final status is still computed by `services/grounding.py` from the
*verified* links, not the LLM's own confidence. See
`services/llm_gateway.py` for the provider-neutral gateway this agent calls
through (OpenAI implemented; swapping providers means one new class, not a
rewrite of the agent).

**Current limitation, stated plainly:** no `OPENAI_API_KEY` is configured in
this environment yet, so the agent has been exercised thoroughly with a fake
gateway (6 unit tests covering the happy path, hallucinated-dataset
rejection, hallucinated-evidence rejection, provider-error fallback, and
no-key fallback) and live-verified end to end via the real API with no key
present (correctly degrades to an honest `UNVERIFIED` claim naming the
ambiguous candidates, rather than crashing or guessing) — but it has not yet
made a real call to OpenAI. That's the one thing blocking it from "Live
External Tested": add `OPENAI_API_KEY` to `backend/.env` and re-run the same
ambiguous scenario (`docs/RUNBOOK.md` has the exact repro steps).

## The Revenue Quality Certification demo scenario — fully reproducible

`revenue_demo/` (seed + 3 dbt models modeling
`raw_orders → stg_orders → int_revenue → fact_revenue`, with the exact
injected defect from Architecture spec §49: `int_revenue.sql` filters
`WHERE status = 'COMPLETE'` instead of `WHERE status IN ('COMPLETE',
'SHIPPED')`) plus `scripts/run_revenue_demo.py`, which drives the *entire*
loop against a running ADE backend and asserts each transition:

1. Provisions a fresh local DuckDB dbt project, installs the demo seed/models.
2. `dbt build` (defect active) → registers the business concept, contract,
   and 8 quality rules (schema, completeness, uniqueness, a business rule,
   transformation-formula correctness, source-target row coverage, net
   revenue reconciliation, gross revenue reconciliation, volume) via the
   real API.
3. Executes all 8 rules for real: 5 PASS, 3 correctly **FAIL** (row
   coverage: 3 orders missing; net revenue off by 380.00 / 37%; gross
   revenue off by 410.00) — the formula and cancelled-order handling are
   correctly reported as fine, isolating the defect to the recognized-status
   filter, exactly matching the spec's intended RCA narrative.
4. Certifies `int_revenue` and `fact_revenue` → both **FAILED**, each with
   an explainable reason naming the exact failing rule.
5. Runs RCA on `fact_revenue` → **SUPPORTED** claim, correctly localizing
   the discrepancy to `int_revenue` via the real lineage path.
6. Proposes a remediation (the exact one-line fix), approves it, applies
   it — a real, narrowly-scoped file patch (rejected if unapproved, if the
   target text isn't found, or isn't unique).
7. `dbt build` again, re-executes all 8 rules → all **PASS**.
8. Re-certifies → both **CERTIFIED**.

Run it yourself: `python3 scripts/run_revenue_demo.py` (backend must
already be running). Confirmed working from a completely clean project
each time, including a regression check for a real bug found while doing
this (below).

## A real bug found and fixed while building this

`evaluate_certification()` and the RCA lineage walk originally matched
rules/certifications by `dataset_ref` (a bare table name like
`int_revenue`) with no project scoping. Running the demo script against a
*second*, separate "Revenue Pipeline" project (after having already created
one by hand) silently conflated the two projects' same-named
`int_revenue`/`fact_revenue` rules — certification reasons listed the same
rule name twice, from two different projects' rows. Fixed by adding
`dbt_project_id` to `Certification` and threading it through
`evaluate_certification()`, the `/api/certifications/evaluate` endpoint, and
both RCA lookup helpers; regression tests added
(`test_certification.py::test_scoped_by_project_when_table_names_collide`,
`test_rca.py::test_locate_root_cause_scopes_by_project`).

## Test suite

`backend/tests/` — 40 tests, all passing (`pytest tests/ -q`): rule
compilation/execution (13), certification derivation incl. project-scoping
regression (7), a real DuckDB adapter against a temp warehouse (5),
grounding status machine (4), deterministic RCA lineage walk incl.
project-scoping regression (5), RCA agent escalation incl. hallucination
rejection and graceful degradation (6).

## Next (in priority order)

1. Add `OPENAI_API_KEY` and live-verify the RCA agent against a real OpenAI
   call (everything else about it is already built and tested).
2. Transformation Intelligence: SQLGlot-based analysis of dbt compiled SQL
   → structured inputs/outputs/CASE/JOIN/FILTER, feeding rule *suggestions*
   (still human/AI-proposed, engine-executed).
3. Quality/test-generation agent: given a business contract in plain
   language, proposes candidate `QualityRule` definitions for human review
   (reuses the same LLM Gateway `rca_agent.py` calls through).
4. Evidence Intelligence: bundle evidence per run, add Tier 1-5 provenance
   so agent claims can be ranked against contradictory lower-tier inference.
5. Hash/bucket reconciliation and key-coverage checks.
6. Project deletion (currently absent for both dbt and Airflow projects —
   demo runs accumulate rows/venvs on disk).
