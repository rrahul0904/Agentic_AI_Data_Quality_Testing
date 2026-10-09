# ADE Local Deployment

The Agentic Data Engineering OS is a local/runtime product. Vercel is not part of the ADE deployment architecture.

The canonical single-machine deployment is `docker-compose.local.yml`. It runs the real FastAPI control plane and the Next.js operator console together, with persistent local state and fail-closed API authentication.

## What runs

| Service | Local address | Responsibility |
| --- | --- | --- |
| `web` | `http://127.0.0.1:3000` | ADE operator console and same-origin API proxy |
| `api` | `http://127.0.0.1:8001` | FastAPI control plane, governed tools, agents, evidence and platform APIs |

Both ports bind to loopback by default. Do not change the bind addresses to `0.0.0.0` merely to make the UI reachable from another machine. For remote access, put an authenticated reverse proxy, VPN, or SSH tunnel in front of the loopback deployment and follow `docs/PRODUCTION_DEPLOYMENT.md`.

## First start

From the repository root:

```bash
bash scripts/ade-local.sh init
bash scripts/ade-local.sh up
```

`init` creates `.env.local` with a random API token and local web credentials. `.env.local` is ignored by Git and should remain private.

`up` performs all of the following before reporting success:

1. validates Docker and Docker Compose v2;
2. validates the Compose configuration;
3. builds the API and web images;
4. starts both services;
5. waits for API and web health checks;
6. sends an authenticated request through the web proxy to the API.

A successful start ends with:

```text
PASS: API health, web health, and authenticated web-to-API proxy
ADE is running locally: http://127.0.0.1:3000
```

## Lifecycle commands

```bash
bash scripts/ade-local.sh status
bash scripts/ade-local.sh smoke
bash scripts/ade-local.sh logs
bash scripts/ade-local.sh down
```

`down` intentionally preserves the named volumes containing ADE state and managed workspaces.

To deliberately remove those volumes:

```bash
bash scripts/ade-local.sh reset
```

`reset` is destructive and is never called by the normal shutdown path.

## Runtime posture

The canonical local stack starts the API with:

- `ADE_RUNTIME_MODE=production`
- `ADE_DEMO_MODE=false`
- `ADE_AUTH_MODE=api_key`
- `ADE_SAFE_MODE=true`
- `ADE_ONLINE_ENABLED=false`
- `ADE_CONNECTOR_WRITE_ENABLED=false`
- filesystem-backed persistent control-plane, quality, investigation and artifact state
- the repository's bundled hospitality project as a filesystem project source

This makes the local deployment operational without pretending that live Snowflake, Airflow, dbt Cloud, external model providers, or other credentials exist. Those integrations should only report live when their separately configured credentials and certification checks succeed.

## Local authentication

The API uses the repository's `ADE_API_KEYS_JSON` contract. The generated credential has an `admin` role and a random token of sufficient length. The Next.js server-side proxy receives the corresponding service token; it does not expose the token to browser JavaScript.

Because the UI proxy has a server-side service credential, **loopback binding is part of the local security boundary**. Any future LAN or Internet exposure must add an authenticated ingress rather than changing the bind address alone.

## Persistence

The stack uses two named Docker volumes:

- `ade-local-state` for SQLite databases and generated evidence/artifacts;
- `ade-local-workspaces` for ADE-managed workspaces.

Normal rebuilds and `down`/`up` cycles keep those volumes. `reset` removes them.

## CI certification

`.github/workflows/local-stack.yml` builds this exact stack on pull requests that modify local deployment/runtime files and runs the same `smoke` command. A green workflow proves that a clean Git checkout can build, boot, become healthy, and complete an authenticated web-to-API request.

It does **not** certify external Snowflake/Airflow/provider integrations; those remain separate live certification gates.

## Vercel

There is intentionally no `vercel.json` in the local-first deployment branch. ADE should not be deployed or certified through Vercel. Previous `ade-prototype-1` and `ade-prototype-1-services` Vercel projects are legacy deployment experiments and should be deleted from the Vercel dashboard.
