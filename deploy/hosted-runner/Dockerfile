FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ADE_PROJECT_ROOT=/workspace

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY scripts/run_hosted_runner.py ./scripts/run_hosted_runner.py

RUN python -m pip install --no-cache-dir . \
    && mkdir -p /data /workspace

VOLUME ["/data", "/workspace"]

CMD ["python", "scripts/run_hosted_runner.py", "--project", "/workspace", "--database", "/data/hosted-runner.db", "--json"]
