# ADE Production + Superiority Certification

This program starts after repository-local competitive parity is green. Its purpose is to separate three different claims that must never be conflated:

1. **Implemented** — the capability exists in source.
2. **Certified local** — the exact Git SHA passed the required local release gates.
3. **Certified external / superior** — a real external execution produced immutable evidence, and for superiority the executed comparative metrics show ADE winning.

## Canonical API

`GET /api/v1/certification/production`

The runtime endpoint is intentionally report-only. It does not certify itself. If `ADE_COMMIT_SHA` is not set to an exact 40-character SHA, the endpoint returns `UNBOUND_RUNTIME`.

For container deployments, `docker-compose.web.yml` forwards:

- `ADE_COMMIT_SHA`
- `ADE_EXTERNAL_ASSURANCE_EVIDENCE`

The external evidence path can point at a JSON artifact mounted into the runtime. Missing evidence is reported as `NOT_RUN_EXTERNAL`; malformed or wrong-SHA evidence is reported as `BLOCKED_EXTERNAL`.

## External evidence contract

Each completed external track must provide:

```json
{
  "status": "PASS_EXTERNAL",
  "commit_sha": "<exact 40-character SHA that was executed>",
  "executed_at": "2026-09-15T03:00:00Z",
  "artifact_uri": "s3://immutable-bucket/path/evidence.json",
  "evidence_sha256": "<64 hex characters>"
}
```

A claimed external PASS without all required fields fails closed. The evidence `commit_sha` must exactly match the SHA being certified; evidence produced by another build is never promoted or rebound to the current runtime.

## Superiority contract

`superior=true` is allowed only for the `cross_product_superiority_benchmark` track when the external evidence is valid, is bound to the exact SHA being certified, and contains executed comparative metrics:

```json
{
  "metrics": {
    "winner": "ADE",
    "ade_score": 0.91,
    "competitor_scores": {
      "competitor-a": 0.81,
      "competitor-b": 0.87
    }
  }
}
```

ADE must have a strictly higher score than every recorded competitor. Local CI, parity, feature count, or self-reported capability matrices cannot set `superior=true`.

## Candidate artifact

Generate a report-only exact-head candidate:

```bash
python scripts/generate_production_certification.py \
  --commit-sha "$(git rev-parse HEAD)" \
  --output artifacts/production/assurance-candidate.json
```

After all required exact-head local release workflows are independently green, the release orchestrator may generate a local-certified artifact with `--local-gate-passed`. That flag must not be used as a substitute for running the required release gates.

External evidence may be supplied with:

```bash
python scripts/generate_production_certification.py \
  --commit-sha "$(git rev-parse HEAD)" \
  --external-evidence /state/external-assurance.json \
  --output artifacts/production/assurance.json
```

## Next execution tracks

The next live work is intentionally outside deterministic repository-only certification:

- Snowflake Cortex Search execution
- Snowflake AI document parsing execution
- Snowflake SPCS/GPU execution
- learned embedding/reranker provider execution
- external LLM provider execution
- managed staging deployment
- cross-product comparative benchmark

Every track stays `NOT_RUN_EXTERNAL` until it has actually run. This makes the certification artifact useful in client and audit settings because absence of credentials or infrastructure cannot silently become a PASS.
