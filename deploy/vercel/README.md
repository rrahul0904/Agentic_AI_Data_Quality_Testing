# ADE Prototype 1.0 — Vercel Services preview

This deployment target is a bounded hosted-preview path for the focused ADE Prototype 1.0 experience.

## Topology

- `web` — the existing Next.js application under `apps/web/`
- `api` — the existing ADE FastAPI image built from `deploy/Dockerfile.api`
- Vercel service binding injects the private `api` service URL into the web service as `ADE_API_URL`.
- Public routing terminates at `web`; the API service is not directly exposed by `vercel.json`.

## Preview security boundary

The Git-linked preview project is protected by Vercel SSO. The initial topology certification uses ADE demo runtime with API auth disabled **only because the API is private/unrouted and the preview entrypoint is SSO-protected**. This is not the production security posture.

Production remains fail-closed and requires:

- `ADE_RUNTIME_MODE=production`
- `ADE_DEMO_MODE=false`
- `ADE_AUTH_MODE=api_key`
- `ADE_API_KEYS_JSON`
- `ADE_API_SERVICE_TOKEN` on the web proxy

Secrets must be injected through the hosting secret store; never commit them.

## Persistence boundary

The first Services preview intentionally keeps SQLite/filesystem adapters only to certify the stable multi-service hosting topology. Durable hosted certification requires managed PostgreSQL for control/investigation/quality state and S3-compatible object storage for generated artifacts.

## Release evidence

A Vercel preview is not considered certified merely because a build exists. Hosted UAT must prove, from one exact Git SHA:

1. web and API health,
2. `/prototype` loads,
3. overview and scenario discovery succeed through the web proxy,
4. an investigation reaches `AWAITING_APPROVAL`,
5. governed approval/execute/verify completes when enabled,
6. evidence receipts persist in the configured durable backends.
