# ADE Reference Capability Superiority Program

> Internal engineering benchmark. Do not present public ADE product documentation as a competitor clone.

## Goal

ADE must reach parity with every capability recorded in
`specs/ADE_REFERENCE_CAPABILITY_SUPERIORITY_LEDGER.json` and then pass a
stronger acceptance gate. "Superior" is not a marketing label: it requires
reference-equivalent behavior plus at least two independently testable ADE
advantages.

## Benchmark sources

The ledger is derived only from current public Snowflake documentation covering:

- CoCo overview and surfaces
- Agent, Plan, Ask, Edit, and Code modes
- CLI/Desktop tools
- subagents
- local and hosted automations
- skills, plugins, hooks, MCP
- agentic browser and notebook
- semantic code/object discovery
- dbt local and Snowflake-managed execution
- app development/deployment
- Cortex Analyst/Search/Agents
- Snowflake AI/ML bundled workflows

The source URLs and verification date are stored in the JSON ledger.

## Scoring

| Score | Meaning |
| --- | --- |
| 0 | GAP — reference behavior is missing |
| 1 | PARITY — behavior exists and is certified |
| 2 | SUPERIOR — parity plus at least two testable ADE advantages |

Every capability has `target_score: 2`.

## Delivery phases

### P0 — control-plane parity and safer execution

P0 closes capability gaps that determine whether ADE can act as a true platform
operator:

- governed Snowflake CREATE/ALTER/DML/DROP
- plan -> approve -> execute -> verify
- environment-aware policy
- exact-statement approval fingerprinting
- RBAC + ADE policy double authorization
- recorded evidence and replay boundaries
- agent/remediation execution loop

The first implementation is in
`src/agentic_data_platform/snowflake/governed_mutation.py`.

Unlike a plain SQL execution permission, ADE binds approval to the normalized
SQL, environment, statement type, object type, and target. A changed statement
therefore produces a different approval fingerprint.

Destructive operations require:

1. ToolRegistry builder/admin mode
2. explicit approval
3. exact fingerprint match
4. explicit destructive confirmation
5. environment policy
6. post-execution verification

Production destructive operations are blocked unless a separate break-glass
policy is explicitly enabled.

### P1 — cross-platform intelligence and autonomy

P1 covers the capabilities that make ADE an operating system rather than a
Snowflake-only assistant:

- cross-system semantic catalog/code search
- dynamic parallel subagents
- custom agent contracts
- scheduled local and hosted investigations
- plugin bundles and lifecycle hooks
- Snowflake-managed dbt
- semantic-layer abstraction
- policy-controlled git/file/shell execution
- account/platform administration

Superiority requires the same agent to reason across Snowflake, Airflow, dbt,
files, business context, and supported warehouses, while retaining deterministic
evidence and replay.

### P2 — developer/AI/ML experience

P2 closes the remaining experience and Snowflake-native development gaps:

- desktop IDE/editor experience
- notebook agent
- agentic browser
- inline visualization
- Streamlit and App Runtime build/deploy
- Cortex Search/Agent administration
- embeddable coding-agent SDK
- Snowpark ML/model registry/GPU jobs
- AI functions and document intelligence

The target is not to reproduce proprietary implementation. ADE implements
publicly observable workflows using its own architecture and adds cross-platform,
provider-neutral, governed verification.

## CI contract

Run:

```bash
python scripts/check_capability_superiority.py --json
pytest -q tests/test_capability_superiority_ledger.py
```

The normal validator ensures the benchmark remains exhaustive and every
capability has an owner, target score, two superiority dimensions, and an
acceptance criterion.

At final closure, run:

```bash
python scripts/check_capability_superiority.py --require-target --json
```

That command must remain red until every ledger entry has actually reached
`ade_current: superior`. Do not weaken the gate to manufacture completion.
