# RE-239 — Snowflake + dbt CI/CD Framework Reverse Engineering

**Source:** https://github.com/Abhibangal/snowflake_dbt  
**Reviewed source HEAD:** `90245c7da9abcf364122aa821b43283b8f93c42e`  
**Canonical destination:** Agentic Data Engineering OS  
**Mode:** clean-room capability donor  
**Status:** reverse engineering started

## 1. Product / framework identity

The source is a repository-oriented Snowflake delivery framework that combines:

- dbt projects deployed as Snowflake dbt project objects;
- SchemaChange-managed Snowflake objects;
- GitHub Actions for pull-request validation and branch-triggered deployment;
- Snowflake Git Repository integration for Python-backed Snowpark procedures and Streamlit applications;
- environment-aware configuration and Jinja substitution;
- repository-wide migration version assignment and immutable versioned migrations;
- dbt run-history logging and one-per-run success/failure notifications.

The reusable value is not the sample business models. The important donor capability is the **hybrid deployment control plane** spanning dbt-owned objects and non-dbt Snowflake objects with deterministic ordering and validation.

## 2. Clean-room / provenance boundary

No LICENSE file was observed in the reviewed source tree at the recorded HEAD. Treat the repository as architecture and behavior evidence only.

For ADE:
- do not copy source code or distinctive implementation text;
- implement equivalent capabilities from the observed behavior and public dbt, Snowflake, SchemaChange, and GitHub Actions contracts;
- retain this source SHA in provenance/evidence;
- keep deployment mutation behind ADE's existing governed execution and approval boundary.

## 3. Repository topology

Observed top-level capability areas:

- `.github/workflows/` — PR validation and deployment workflows
- `dbt/` — dbt project, sources, transformations, consumption models, macros, snapshots, analyses
- `deployment/` — orchestration, config loading, schema discovery, version assignment, Snowflake connectivity, validation
- `snowflake/` — non-dbt object families such as procedures, functions, tasks, streams, stages, pipes, dynamic tables, grants, Snowpark, and Streamlit
- `python/` — external Python job placeholder area
- `common/` — shared logging helper
- `data_files/` — sample dimensional/fact CSVs
- `docs/` — architecture assets and developer guidance

## 4. Core ownership rule

The central architectural rule is a split of responsibility:

- **dbt owns tables and views** under the dbt model graph.
- **SchemaChange owns non-dbt Snowflake objects** such as procedures, grants, tasks, stages, Snowpark objects, and Streamlit DDL.

PR validation enforces this ownership boundary.

This is highly reusable in ADE because mixed repositories otherwise suffer from ambiguous ownership, duplicate DDL, and deployment-order conflicts.

## 5. Deployment dependency graph

The source resolves circular dependencies by splitting deployment into three deterministic phases:

1. **Pre-dbt SchemaChange**
   - deploy supporting objects that dbt hooks can call;
   - examples include logging/notification stored procedures.

2. **dbt deployment**
   - render environment-specific template values;
   - publish the dbt project;
   - execute/compile according to Snowflake dbt project behavior.

3. **Post-dbt SchemaChange**
   - deploy objects that depend on dbt-created relations;
   - the source currently classifies dynamic tables as post-dbt.

This phase graph is more important than the specific object list. ADE should represent the graph as explicit dependency metadata rather than a hard-coded product assumption.

## 6. Branch and environment model

Observed mapping:

- `dev` → DEV
- `main` → PROD

A merge/push to those branches triggers deployment. PR validation runs before merge and is intentionally Snowflake-independent.

Environment-specific database names, warehouses, dbt targets, Git branches, access roles, and change-history tables are resolved from configuration.

## 7. Folder-driven target discovery

Non-dbt objects follow a path-derived target model broadly shaped as:

`snowflake/<object_type>/<logical_database>/<schema>/...`

The logical database layer is combined with environment to derive the Snowflake database. Schema comes from the directory. Deployment order is config-driven.

Useful clean-room ADE capability:
- repository scan;
- object-family classification;
- target resolution;
- dependency graph;
- policy violations;
- deterministic deploy plan.

## 8. Migration/version model

The source distinguishes:

- versioned migrations;
- repeatable migrations;
- unassigned version placeholders.

CI assigns versions to placeholders after merge, using repository history and a configured starting prefix. Already-deployed versioned files are intended to be immutable, and duplicate version numbers are rejected.

Important operational characteristic: the deployment workflow can commit assigned versions back to the branch. ADE should analyze this pattern but should not silently mutate Git history. Any equivalent mutation belongs behind an explicit governed action.

## 9. PR validation gates

The source implements offline repository checks including:

- required project/folder structure;
- migration naming/version format;
- duplicate versions;
- edits to immutable migrations;
- database/schema path validity;
- ownership violations for tables/views;
- grant-role configuration;
- hardcoded environment-specific database names;
- hardcoded warehouse names;
- Streamlit path/config checks;
- dbt project checks.

These are a strong donor for ADE's deterministic PR reviewer because they require no live Snowflake credentials.

## 10. dbt project model

Observed logical layers:

- source/raw declarations;
- transform/cleansing models;
- consumption dimensions/facts;
- ephemeral models;
- snapshots;
- macros;
- analyses.

The dbt directory is a **deployment template**, not a directly runnable standalone project, because deployment-time values such as environment database mappings are rendered before dbt evaluates its own macros.

ADE should detect this distinction when analyzing a repository and avoid falsely reporting a templated dbt project as locally runnable.

## 11. Incremental and SCD patterns

The sample transforms demonstrate append/merge incremental strategies and SCD2 patterns.

Important observed risk:
- some incremental filtering operates at date granularity with a strict greater-than watermark;
- a second batch on the same calendar day can therefore be missed.

ADE should flag time-granularity mismatches between source cadence and incremental predicates.

The repository also contains:
- a dbt SCD2 macro path;
- a Snowpark-based SCD2 rebuild utility that stages the rebuilt result and swaps it into place.

The swap pattern is useful; however, dynamically supplied identifiers require validation and safe quoting before any governed reusable implementation.

## 12. Logging and notification contract

At dbt run end, the source:

- records one audit row per dbt result;
- builds a run-scoped ID from invocation and node identity;
- maps execution status;
- records duration, rows affected, and messages;
- sends exactly one success or failure notification for a real data run.

The macros intentionally avoid compile/parse-only executions to prevent false audit rows and deployment-time emails.

Known semantic caveat:
- adapter row counts do not mean the same thing for every dbt materialization, so ADE should preserve row-count provenance rather than treating all values as equivalent.

## 13. Snowpark pattern

A Python handler is versioned in Git and imported by a Snowflake procedure via the Snowflake Git Repository integration.

Useful donor behaviors:
- Git-backed Python source provenance;
- handler/DDL separation;
- target rebuild into staging followed by atomic-style table swap.

Needed hardening:
- identifier validation and quoting;
- bounded permissions;
- input contract validation;
- evidence for swap/drop failure recovery.

## 14. Streamlit in Snowflake pattern

The source separates:
- application Python source;
- CREATE STREAMLIT DDL;
- grants.

The Python is sourced through Snowflake Git Repository paths, while DDL is deployed via SchemaChange. This mirrors the Snowpark code/DDL separation.

ADE can generalize this as a **code artifact + deployable registration object + grants** pattern.

## 15. CI/CD mechanics

The deployment workflow:

- checks out full history;
- installs pinned Python dependencies;
- installs Snowflake CLI separately to avoid dependency conflicts;
- creates a private key file from GitHub secrets;
- assigns migration versions;
- commits version renames when necessary;
- runs the orchestrated deployment;
- deletes the local private key file in cleanup.

Concurrency is configured per branch so same-branch deployments do not overlap.

## 16. Security and portability gaps

The following should be treated as donor gaps, not copied defaults:

1. deployment config uses `ACCOUNTADMIN`;
2. configured warehouse defaults to a generic `COMPUTE_WH`;
3. notification procedures contain a hardcoded email recipient;
4. notification integration name is hardcoded;
5. production is tied directly to the `main` branch;
6. direct pushes to protected deployment branches can still trigger deployment unless branch protection is enforced externally;
7. dynamic identifiers in utility procedures need stronger validation;
8. several supported object-family folders contain placeholders rather than end-to-end examples;
9. no broad repository-level unit-test suite for the Python deployment engine was observed in the reviewed tree;
10. the dbt template cannot be executed directly without the repository-specific render step.

## 17. Capability mapping into Agentic Data Engineering OS

### Phase A — deterministic hybrid repository analyzer
Implement read-only analysis that emits:
- object ownership classification;
- path-derived database/schema targets;
- pre-dbt/dbt/post-dbt dependency phases;
- migration inventory;
- hardcoded environment/warehouse/role findings;
- dbt-template/runtime distinction;
- portability and least-privilege findings.

### Phase B — deployment-plan policy engine
Add:
- configurable ownership policies;
- object dependency rules;
- immutable migration checks;
- version collision detection;
- deployment-order validation;
- environment-diff checks;
- evidence bundle output.

### Phase C — PR review integration
Use ADE's existing GitHub review layer to:
- analyze changed files only;
- detect unsafe migration edits;
- recommend deterministic validation;
- report blast radius;
- remain idempotent and read-only by default.

### Phase D — governed execution adapters
Only after repository-level validation:
- dry-run external commands;
- require explicit approval for mutations;
- require least-privilege connection profiles;
- stamp exact Git SHA and deployment evidence;
- fail closed when Snowflake credentials or target evidence are unavailable.

### Phase E — live certification
Separate from repository completion:
- execute against an authorized Snowflake environment;
- capture exact command/version/target evidence;
- verify dbt and SchemaChange phase ordering;
- verify migration history;
- verify rollback/recovery behavior;
- verify least-privilege role boundaries.

## 18. Initial acceptance criteria

The first ADE implementation slice is complete only when:

- the donor snapshot SHA is retained;
- analysis works without Snowflake credentials;
- dbt-owned vs non-dbt-owned objects are classified deterministically;
- a stable phase plan is produced;
- unsafe hardcoded environment/warehouse/role patterns are detected;
- migration immutability/version conflicts are detected;
- results are exposed through ADE's normal evidence contract;
- tests cover representative hybrid repositories;
- no live deployment is claimed from static analysis alone.

## 19. Current status

Reverse engineering is **started**. The architecture, deployment phases, validation model, migration semantics, dbt runtime behavior, Snowpark/Streamlit patterns, and key production gaps have been captured.

Next concrete engineering action: implement the read-only hybrid deployment analyzer and evidence schema in ADE, then add tests before introducing any Snowflake mutation path.
