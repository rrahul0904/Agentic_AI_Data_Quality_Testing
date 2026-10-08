FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8001

WORKDIR /app
COPY . .

# Git is a runtime dependency only for managed HTTPS project materialization.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Keep this root Dockerfile behaviorally identical to deploy/Dockerfile.api.
# Vercel Services requires a container entrypoint literally named Dockerfile/Containerfile.
RUN python -m pip install --no-cache-dir ".[cloud]" "dbt-snowflake>=1.9,<2" \
    && python scripts/parse_dbt.py
RUN mkdir -p /state /workspaces /app/.ade /app/hospitality-snowflake-data-platform/.ade \
    && groupadd --gid 10001 ade \
    && useradd --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin ade \
    && chown -R ade:ade /app /state /workspaces

ENV ADE_DATABASE_PATH=/state/control-plane.db \
    ADE_QUALITY_DATABASE=/state/quality.db \
    ADE_INVESTIGATION_DATABASE=/state/investigations.db \
    ADE_DEMO_PROJECT=/app/hospitality-snowflake-data-platform \
    ADE_WORKSPACE_ROOT=/workspaces \
    PYTHONPATH=/app/src

EXPOSE 8001

USER ade

CMD ["sh", "-c", "python -m uvicorn agentic_data_platform.api.hosted_app:app --host 0.0.0.0 --port ${PORT:-8001}"]
