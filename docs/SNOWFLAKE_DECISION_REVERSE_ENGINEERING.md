# Snowflake Decision Reverse Engineering — Bounded Decision Engine

Status: implementation slice built on `reverse/snowflake-decision-engine`; repository CI, Docker, cloud, and restart/durability verification remain separate gates.

Canonical product: **PRD-0046 — Agentic Data Engineering OS**

Source intake: `https://lnkd.in/p/gxETfSu9`

## 1. Source-verified capability

Snowflake announced **Snowflake Decision** in October 2026 as a private-preview model used through Cortex AI Functions / `AI_COMPLETE` for bounded, high-volume decision tasks. Public Snowflake material describes three core assessment shapes:

1. **Choice** — select from a fixed option set and expose probabilities/confidence.
2. **Score** — score against an ordered rubric and expose per-level probabilities/confidence; the numeric result is probability weighted.
3. **True-or-false assessment** — return the probability that a specified statement is true.

The source positioning is classification, scoring, filtering, and routing over data, including table/query-oriented use.

Primary public sources used for this clean-room analysis:

- Snowflake blog, *Introducing Snowflake Decision in Cortex AI Functions* (2026-10-08): `https://www.snowflake.com/en/engineering-blog/snowflake-decision-cortex-ai-functions/`
- Snowflake release notes, Snowflake Decision private preview (2026-10-07): `https://docs.snowflake.com/en/release-notes/2026/other/2026-10-07-snowflake-decision`
- Snowflake `AI_COMPLETE` documentation: `https://docs.snowflake.com/en/sql-reference/functions/ai_complete-single-string`

### Evidence boundary

`SOURCE_VERIFIED` means the public source demonstrates or documents the source product. It does **not** prove this repository implements that behavior.

## 2. Open implementation/reference donor

The open `Mapika/decider` project and `decider-2b` model are useful as an implementation/benchmark reference and declare Apache-2.0 licensing. They are **not Snowflake-owned code** and they are not evidence of parity with Snowflake Decision.

Donor: `https://github.com/MapikaAI/decider`

`DONOR_VERIFIED` means the donor can inform architecture, tests, or benchmarks. It does **not** establish that ADE OS has implemented or matched either donor or Snowflake behavior.

## 3. Clean-room reconstruction target

We reconstruct the transferable product idea as a **provider-neutral Bounded Decision Engine** rather than a Snowflake-specific clone.

```text
Caller / Agent / Data-quality workflow
              |
              v
      Bounded Decision Contract
   Choice | Score | True-or-False
              |
              v
        Decision Policy Gate
 confidence threshold | fallback | abstain
              |
              v
       Provider-neutral Engine
         /               \
        v                 v
Deterministic local   Provider adapters
baseline              (Snowflake Decision,
                       future LLM/model providers)
              |
              v
 validation + trace + batch order preservation
```

The core contract is intentionally above the existing ADE provider layer. Snowflake is an adapter, not the platform boundary.

## 4. Implemented contracts

Package: `src/agentic_data_platform/decision`

### Choice

Input:

- arbitrary payload
- bounded question
- at least two unique declared options

Output invariants:

- selected key must belong to the declared options unless the policy abstains
- probability keys exactly match declared option order
- every probability is in `[0, 1]`
- probabilities sum to `1.0`
- confidence is in `[0, 1]`

### Score

Input:

- arbitrary payload
- bounded question
- at least two unique ordered rubric levels
- rubric numeric values must be strictly increasing

Output invariants:

- level-probability keys exactly match the rubric order
- probabilities sum to `1.0`
- score is inside the rubric range
- score must equal the probability-weighted rubric value
- confidence is in `[0, 1]`

### True-or-False

Input:

- arbitrary payload
- one non-empty statement

Output invariants:

- probability that the statement is true is in `[0, 1]`
- confidence is in `[0, 1]`

## 5. Governance improvements over the source pattern

The reconstruction adds platform controls required by ADE OS:

- **provider neutrality** — decision semantics do not depend on Snowflake transport
- **fail-closed validation** — malformed provider distributions/results are rejected
- **confidence thresholding** — callers can set a minimum confidence
- **abstention** — below-threshold results can become no-decision rather than fabricated certainty
- **fallback routing** — a second registered provider can be tried and the trace records the originating provider
- **audit trace** — every result records provider/model metadata
- **offline deterministic baseline** — `EvidenceOverlapProvider` supports deterministic smoke tests and no-cloud operation; it is explicitly not a semantic-parity claim
- **batch order preservation** — batch APIs return results in input order

## 6. Snowflake private-preview adapter boundary

`SnowflakeDecisionProvider` intentionally does **not** invent a private-preview request or SQL schema.

The adapter accepts an injected canonical executor:

```text
executor(operation, canonical_request) -> canonical_result
```

Operations are `choice`, `score`, and `truth`. The caller/account-specific executor is responsible for translating the canonical contract into the Snowflake invocation available to that account and returning a normalized mapping.

If no executor is configured, the adapter raises `DecisionProviderUnavailable` and reports that the private-preview transport is unavailable. This preserves ADE OS's fail-closed rule.

A live Snowflake SQL executor should only be added after we have account-accessible private-preview invocation documentation/credentials and can capture exact request/response fixtures.

## 7. First ADE OS use cases

High-value integrations for PRD-0046:

- data-quality finding classification and triage
- RCA hypothesis ranking/routing
- operational severity scoring
- remediation-plan selection
- autonomous-action gate: allow / deny / escalate as a bounded choice
- migration finding prioritization
- policy verdict probability before protected actions

The decision engine should advise or gate existing governed workflows; it must not bypass approval boundaries for protected writes/deployments.

## 8. Acceptance tests

| Acceptance criterion | Current evidence |
| --- | --- |
| Choice cannot return undeclared option | Implemented validator + unit test path |
| Choice probabilities sum to 1 | Implemented validator + unit test |
| Score respects ordered rubric | Contract validation + unit test |
| Score is probability-weighted | Implemented validator + unit test |
| True probability is bounded | Implemented validator + unit test |
| Malformed provider result fails closed | Unit test |
| Confidence threshold can abstain | Unit test |
| Fallback provider is traceable | Unit test |
| Batch result order is stable | Unit test |
| Snowflake unavailable without executor | Unit test |
| Snowflake transport is not guessed | Adapter requires injected executor + unit test |

Isolated local evidence from the implementation slice before push: **11 tests passed** (`pytest`, 2026-10-09). Repository-wide CI remains a distinct verification gate.

## 9. Verification matrix

| Roadmap stage | State | Evidence / next proof |
| --- | --- | --- |
| Intake | PASS | LinkedIn source resolved; official Snowflake sources cross-checked |
| Analysis | PASS | Source primitives + clean-room opportunity mapped |
| Spec | PASS | This document defines target architecture and non-goals |
| Contract | PASS | Typed bounded contracts + invariants committed on branch |
| Implement | PASS (slice) | Decision engine, deterministic baseline, Snowflake adapter boundary |
| Test — isolated | PASS | 11/11 tests before branch push |
| Test — repository CI | PENDING | Must use PR workflow evidence against exact head SHA |
| Docker | NOT VERIFIED | Run repository container verification after CI |
| Cloud / live provider | NOT VERIFIED | Requires supported environment/private-preview access |
| Restart / reload / durability | NOT VERIFIED | Capture after a deployable service exposure exists |
| Docs | PASS (slice) | Clean-room/evidence ledger recorded here |

## 10. Next build slices

1. Wire decision operations into the governed tool registry/API/CLI without creating a parallel service.
2. Add golden fixtures and calibration metrics (accuracy, Brier/log loss where labels exist, abstention coverage, fallback rate).
3. Add domain fixtures for DQ triage, RCA routing, and remediation gating.
4. Add a Snowflake executor only when private-preview transport is verifiable from the actual account/docs.
5. Certify through repository CI, Docker, and deployment/restart gates before calling the capability complete or live.

## Non-goals

This work does not claim:

- Snowflake model weights or internal inference architecture have been reproduced.
- ADE OS matches Snowflake Decision quality, throughput, cost, or calibration.
- Mapika/decider is Snowflake-owned.
- A live Snowflake private-preview integration exists without account-level executor evidence.
- Source/donor behavior is evidence of ADE implementation behavior.
