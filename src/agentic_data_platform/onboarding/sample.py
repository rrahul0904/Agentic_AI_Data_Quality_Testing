"""Safe deterministic starter dbt/DuckDB sample materialization."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any


SAMPLE_VERSION = "1.0.0"
DEFAULT_SAMPLE_NAME = "agentic-data-sample-dbt"
_FILES = {
    "dbt_project.yml": """name: agentic_data_sample
version: '1.0'
config-version: 2
profile: agentic_data_sample
model-paths: ['models']
seed-paths: ['seeds']
models:
  agentic_data_sample:
    +materialized: view
""",
    "profiles.yml": """agentic_data_sample:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: sample.duckdb
      threads: 4
""",
    "models/stg_orders.sql": """select
  cast(order_id as integer) as order_id,
  cast(customer_id as integer) as customer_id,
  cast(amount as decimal(18,2)) as amount,
  cast(order_date as date) as order_date
from {{ ref('raw_orders') }}
""",
    "models/fct_orders.sql": """select
  order_id,
  customer_id,
  amount,
  order_date
from {{ ref('stg_orders') }}
""",
    "models/schema.yml": """version: 2
models:
  - name: fct_orders
    columns:
      - name: order_id
        tests:
          - not_null
          - unique
""",
    "seeds/raw_orders.csv": """order_id,customer_id,amount,order_date
1,101,19.95,2026-01-01
2,102,49.50,2026-01-02
3,101,7.25,2026-01-03
""",
    "README.md": """# Agentic Data Engineering starter sample

A deterministic local dbt + DuckDB project for onboarding, SQL review,
lineage, tests, metadata indexing, and data-diff demonstrations.
""",
}


def _validate_name(name: str) -> str:
    value = name.strip()
    if (
        not value
        or value.startswith(".")
        or "/" in value
        or "\\" in value
        or ".." in value
        or not re.fullmatch(r"[A-Za-z0-9._-]+", value)
    ):
        raise ValueError(
            "preferred target name must be one safe path segment"
        )
    return value


def _manifest(path: Path) -> dict[str, Any] | None:
    manifest = path / ".sample-manifest.json"
    if not manifest.is_file():
        return None
    try:
        value = json.loads(manifest.read_text())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _write_sample(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for relative, content in _FILES.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (target / ".sample-manifest.json").write_text(
        json.dumps(
            {
                "name": DEFAULT_SAMPLE_NAME,
                "version": SAMPLE_VERSION,
                "files": sorted(_FILES),
            },
            indent=2,
        )
        + "\n"
    )


def materialize_sample(
    *,
    home: str | Path | None = None,
    preferred_target_name: str = DEFAULT_SAMPLE_NAME,
    allow_in_place_upgrade: bool = False,
    install_alongside: bool = False,
) -> dict[str, Any]:
    root = Path(home).expanduser().resolve() if home else Path.home().resolve()
    if root == Path("/"):
        raise ValueError("refusing to materialize starter sample under filesystem root")
    name = _validate_name(preferred_target_name)
    target = root / name
    suffix = 0
    note = ""

    if target.exists():
        manifest = _manifest(target)
        if manifest and manifest.get("version") == SAMPLE_VERSION:
            return {
                "status": "PASS",
                "path": str(target),
                "reused": True,
                "suffix": 0,
                "version": SAMPLE_VERSION,
                "note": "existing starter sample is current",
                "dbt_present": shutil.which("dbt") is not None,
                "duckdb_present": shutil.which("duckdb") is not None,
            }
        if install_alongside:
            suffix = 2
            while (root / f"{name}-{suffix}").exists():
                suffix += 1
            target = root / f"{name}-{suffix}"
            note = "installed alongside existing sample"
        elif allow_in_place_upgrade:
            if target.is_symlink():
                raise ValueError("refusing to replace symlinked sample target")
            shutil.rmtree(target)
            note = "upgraded existing sample in place"
        else:
            return {
                "status": "VERSION_CONFLICT",
                "path": str(target),
                "reused": True,
                "suffix": 0,
                "version": SAMPLE_VERSION,
                "existing_version": manifest.get("version") if manifest else None,
                "note": (
                    "existing target differs from current sample; choose "
                    "allow_in_place_upgrade or install_alongside"
                ),
                "dbt_present": shutil.which("dbt") is not None,
                "duckdb_present": shutil.which("duckdb") is not None,
            }

    _write_sample(target)
    return {
        "status": "PASS",
        "path": str(target),
        "reused": False,
        "suffix": suffix,
        "version": SAMPLE_VERSION,
        "note": note or "starter sample materialized",
        "models": 2,
        "seed_tables": 1,
        "dbt_present": shutil.which("dbt") is not None,
        "duckdb_present": shutil.which("duckdb") is not None,
    }
