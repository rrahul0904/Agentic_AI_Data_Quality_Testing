#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"BLOCKED_EXTERNAL: required environment variable is missing: {name}")
    return value


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value):
        raise SystemExit(f"unsafe Snowflake identifier: {value!r}")
    return value.upper()


def run(argv: list[str], cwd: Path) -> dict:
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=600)
    result = {
        "command": argv,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-6000:],
        "stderr": completed.stderr[-6000:],
    }
    if completed.returncode != 0:
        raise SystemExit(json.dumps({"status": "FAIL", **result}, indent=2))
    return result


def write_seed(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    path.write_text(
        "payment_id,amount,status,updated_at\n"
        + "\n".join(",".join(row) for row in rows)
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if os.getenv("ADE_DBT_LIVE_MUTATION_APPROVED", "").lower() != "true":
        raise SystemExit(
            "BLOCKED_EXTERNAL: set ADE_DBT_LIVE_MUTATION_APPROVED=true to authorize temporary Snowflake dbt objects"
        )

    required("SNOWFLAKE_ACCOUNT")
    required("SNOWFLAKE_USER")
    required("SNOWFLAKE_PASSWORD")
    required("SNOWFLAKE_WAREHOUSE")
    database = identifier(required("SNOWFLAKE_DATABASE"))
    role = os.getenv("SNOWFLAKE_ROLE", "")
    schema = identifier(
        os.getenv("ADE_DBT_LIVE_SCHEMA")
        or ("ADE_AGENTIC_E2E_" + uuid4().hex[:10])
    )

    try:
        import snowflake.connector
    except ImportError as exc:
        raise SystemExit("snowflake-connector-python is required") from exc

    connection = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=database,
        role=role or None,
    )

    try:
        cursor = connection.cursor()
        cursor.execute(f"CREATE SCHEMA {database}.{schema}")
        create_schema_query_id = cursor.sfqid
        cursor.close()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            profiles = root / "profiles"
            (project / "models").mkdir(parents=True)
            (project / "seeds").mkdir()
            profiles.mkdir()

            (project / "dbt_project.yml").write_text(
                """name: agentic_live_e2e
version: 1.0.0
config-version: 2
profile: agentic_live_e2e
model-paths: ["models"]
seed-paths: ["seeds"]
models:
  agentic_live_e2e:
    +schema: LIVE
""",
                encoding="utf-8",
            )
            (profiles / "profiles.yml").write_text(
                f"""agentic_live_e2e:
  target: live
  outputs:
    live:
      type: snowflake
      account: "{{{{ env_var('SNOWFLAKE_ACCOUNT') }}}}"
      user: "{{{{ env_var('SNOWFLAKE_USER') }}}}"
      password: "{{{{ env_var('SNOWFLAKE_PASSWORD') }}}}"
      role: "{{{{ env_var('SNOWFLAKE_ROLE', '') }}}}"
      warehouse: "{{{{ env_var('SNOWFLAKE_WAREHOUSE') }}}}"
      database: "{database}"
      schema: "{schema}"
      threads: 2
""",
                encoding="utf-8",
            )
            (project / "models" / "stg_payments.sql").write_text(
                """{{ config(materialized='view') }}
select
  payment_id,
  amount::number(18,2) as amount,
  status,
  updated_at::timestamp_ntz as updated_at
from {{ ref('payments') }}
""",
                encoding="utf-8",
            )
            (project / "models" / "fact_payment.sql").write_text(
                """{{ config(
    materialized='incremental',
    unique_key='payment_id',
    incremental_strategy='merge'
) }}
select payment_id, amount, status, updated_at
from {{ ref('stg_payments') }}
{% if is_incremental() %}
where updated_at >= dateadd(day, -7, (select coalesce(max(updated_at), '1900-01-01'::timestamp_ntz) from {{ this }}))
{% endif %}
""",
                encoding="utf-8",
            )
            (project / "models" / "schema.yml").write_text(
                """version: 2
models:
  - name: fact_payment
    columns:
      - name: payment_id
        tests:
          - not_null
          - unique
""",
                encoding="utf-8",
            )

            seed_path = project / "seeds" / "payments.csv"
            initial_rows = [
                ("p-1001", "100.00", "COMPLETE", "2026-09-07 20:00:00"),
                ("p-1002", "200.00", "COMPLETE", "2026-09-07 21:00:00"),
                ("p-1003", "300.00", "SHIPPED", "2026-09-07 22:00:00"),
            ]
            write_seed(seed_path, initial_rows)

            base = ["dbt", "--no-use-colors"]
            seed_result = run(base + ["seed", "--project-dir", str(project), "--profiles-dir", str(profiles)], project)
            first_build = run(base + ["build", "--project-dir", str(project), "--profiles-dir", str(profiles)], project)

            updated_rows = initial_rows + [
                ("p-1004", "400.00", "COMPLETE", "2026-09-07 23:00:00"),
            ]
            write_seed(seed_path, updated_rows)
            reseed = run(
                base + [
                    "seed", "--full-refresh",
                    "--project-dir", str(project),
                    "--profiles-dir", str(profiles),
                ],
                project,
            )
            selective = run(
                base + [
                    "build",
                    "--select", "fact_payment",
                    "--project-dir", str(project),
                    "--profiles-dir", str(profiles),
                ],
                project,
            )

            cursor = connection.cursor()
            relation = f"{database}.{schema}_LIVE.FACT_PAYMENT"
            cursor.execute(f"SELECT COUNT(*), SUM(amount), COUNT_IF(payment_id IS NULL) FROM {relation}")
            count, amount, null_keys = cursor.fetchone()
            certification_query_id = cursor.sfqid
            cursor.close()

            if int(count) != 4 or float(amount) != 1000.0 or int(null_keys) != 0:
                raise SystemExit(
                    f"live dbt recertification failed: count={count}, amount={amount}, null_keys={null_keys}"
                )

            run_results_path = project / "target" / "run_results.json"
            run_results = json.loads(run_results_path.read_text()) if run_results_path.is_file() else {}
            selected_nodes = [
                item.get("unique_id")
                for item in run_results.get("results", [])
                if item.get("unique_id")
            ]
            if not any(str(node).endswith("fact_payment") for node in selected_nodes):
                raise SystemExit(f"selective dbt run did not include fact_payment: {selected_nodes}")

            print(json.dumps({
                "status": "PASS",
                "mode": "LIVE_DBT_SNOWFLAKE",
                "schema": schema,
                "create_schema_query_id": create_schema_query_id,
                "initial_build": first_build["exit_code"],
                "incremental_materialization": "PASS",
                "selective_selector": "fact_payment",
                "selective_rerun": "PASS",
                "selected_nodes": selected_nodes,
                "raw_seed_rows": 4,
                "fact_rows": int(count),
                "fact_amount": float(amount),
                "dbt_tests": "PASS",
                "post_remediation_certification": "CERTIFIED",
                "certification_query_id": certification_query_id,
                "seed_commands": [seed_result["exit_code"], reseed["exit_code"]],
            }, indent=2, sort_keys=True))
    finally:
        cleanup = connection.cursor()
        try:
            cleanup.execute(f"DROP SCHEMA IF EXISTS {database}.{schema} CASCADE")
        finally:
            cleanup.close()
            connection.close()


if __name__ == "__main__":
    main()
