# Production Deployment

This document describes the fail-closed production deployment contract for ADE OS.

## Production invariants

Production must satisfy all of the following:

- `ADE_RUNTIME_MODE=production`
- `ADE_DEMO_MODE=false`
- `ADE_AUTH_MODE=api_key`
- `ADE_API_KEYS_JSON` contains authenticated API principals with explicit `analyst`, `builder`, or `admin` roles
- the browser-facing console is authenticated with `ADE_WEB_AUTH_MODE=basic`
- `ADE_WEB_USERS_JSON` maps each web user to a server-held API credential
- the backend API port is not published directly by the production compose stack
- mutating tool calls use a persisted, exact-tool, exact-run approval record
- client-supplied `approved=true` is never trusted in authenticated production mode
- production approvals expire within 24 hours and are consumed after a successful invocation
- the deployment is stamped with the exact `ADE_COMMIT_SHA`

The application refuses to start in production when demo mode is enabled, API authentication is disabled, or no API credentials are configured.

## Credentials

Use secret storage supplied by the deployment platform. Do not commit either JSON value.

Example API principal structure:

```json
{
  "analyst-key": {
    "token": "<long-random-token>",
    "subject": "analyst@example.com",
    "role": "analyst"
  },
  "builder-key": {
    "token": "<different-long-random-token>",
    "subject": "builder@example.com",
    "role": "builder"
  },
  "admin-key": {
    "token": "<different-long-random-token>",
    "subject": "admin@example.com",
    "role": "admin"
  }
}
```

Example browser user mapping:

```json
{
  "analyst-user": {
    "password": "<strong-password>",
    "api_token": "<analyst-token-from-ADE_API_KEYS_JSON>"
  },
  "builder-user": {
    "password": "<strong-password>",
    "api_token": "<builder-token-from-ADE_API_KEYS_JSON>"
  },
  "admin-user": {
    "password": "<strong-password>",
    "api_token": "<admin-token-from-ADE_API_KEYS_JSON>"
  }
}
```

The API token remains on the Next.js server. The browser authenticates to the web service and the proxy converts that authenticated web identity into the corresponding backend Bearer token.

## Required environment

```bash
export ADE_API_KEYS_JSON='...'
export ADE_WEB_USERS_JSON='...'
export ADE_PROJECT_ROOT_HOST=/absolute/path/to/the/managed/project
export ADE_COMMIT_SHA=<exact-git-sha>

# Optional host binding. Keep loopback when TLS/auth is terminated by a reverse proxy.
export ADE_WEB_BIND=127.0.0.1
export ADE_WEB_PORT=3000
```

## Start production

```bash
docker compose -f docker-compose.production.yml up -d --build
```

The API is available only on the internal Compose network. Only the web service publishes a host port.

The production web endpoint must be placed behind HTTPS/TLS before use outside a trusted host. Basic authentication credentials must never traverse plaintext HTTP on an untrusted network.

## Health verification

The web health endpoint intentionally remains unauthenticated for orchestrator probes:

```bash
curl -fsS http://127.0.0.1:3000/api/healthz
```

All product pages and proxied API routes require authentication.

```bash
curl -u '<user>:<password>' http://127.0.0.1:3000/
curl -u '<user>:<password>' http://127.0.0.1:3000/api/ade/api/v1/domains
```

## Production approval flow

A mutating action requires two separate identities in the normal production path:

1. A builder creates or uses a run.
2. An admin creates an approval scoped to the exact registered tool, run, environment, and expiration.
3. The builder invokes the tool with `run_id` and `approval_id`.
4. ADE validates the approval server-side.
5. After a successful invocation the approval is marked used and cannot be replayed.

Example run:

```bash
curl -u 'builder:<password>' \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"prod-project","environment_id":"prod","intent":"approved change"}' \
  http://127.0.0.1:3000/api/ade/runs
```

Example approval:

```bash
curl -u 'admin:<password>' \
  -H 'Content-Type: application/json' \
  -d '{
    "run_id":"<run-id>",
    "approved_by":"ignored-in-production",
    "scope":"dbt_next_state_execute",
    "action":"execute",
    "environment":"prod",
    "expires_at":"<future-ISO-8601-within-24-hours>"
  }' \
  http://127.0.0.1:3000/api/ade/approvals
```

The authenticated admin identity becomes the authoritative `approved_by` value.

A request that merely submits `"approved": true` is rejected in authenticated production mode.

## Certification

The `production-security` GitHub Actions workflow boots `docker-compose.production.yml` and proves:

- unauthenticated product access is rejected;
- authenticated read access succeeds;
- an analyst cannot escalate to admin actor mode;
- a builder cannot create an admin approval;
- an admin-issued approval is identity-bound in evidence;
- a builder can execute the approved dry-run;
- the approval is consumed and replay is rejected;
- production images and proxy paths start successfully.

This runs in addition to the existing integrated-platform, web E2E, Snowflake local certification, competitive certification, and ADE capability regression workflows.

## External production evidence

Repository certification is necessary but does not prove a customer environment. Before declaring a specific hosted environment live, retain evidence for the deployed exact SHA covering:

- TLS/ingress or load-balancer configuration;
- production hostname health/readiness;
- authenticated browser verification;
- secret-manager injection;
- persistent volume/database durability;
- target warehouse credentials and least-privilege roles;
- live Snowflake certification when Snowflake is enabled;
- backup/restore and rollback procedure;
- monitoring/logging/alerting integration.

Missing external evidence must remain explicitly marked as external rather than being inferred from repository CI.
