# Hosted ADE Runner

This directory packages the durable ADE runner as a long-running container.

The worker uses the same `ToolRegistry` as local ADE, so hosting the worker does not grant extra permissions. Actor mode, environment, and explicit approval are persisted with each queued job and are checked again when the worker leases it.

## Local container smoke

```bash
docker compose -f deploy/hosted-runner/docker-compose.yml up --build
```

State is persisted under `/data/hosted-runner.db`. The project is mounted at `/workspace`.

For a managed container platform, build `deploy/hosted-runner/Dockerfile`, attach a persistent volume at `/data`, make the ADE project available at `/workspace`, and provide only the external credentials needed by the tools that runner is allowed to execute.

Do not bake warehouse/API credentials into the image. Use the hosting platform secret store.
