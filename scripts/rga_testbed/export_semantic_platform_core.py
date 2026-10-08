#!/usr/bin/env python3
"""Export a standalone governed-semantic platform core without the RGA workload pack."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "examples" / "banking_semantic_contract.yml"
DEFAULT_OUTPUT = ROOT / "artifacts" / "semantic_platform_core"

CORE_FILES = (
    "analyze_workload.py",
    "build_certification_report.py",
    "build_semantic_release.py",
    "capture_excel_parity_evidence.py",
    "capture_power_bi_parity_evidence.py",
    "capture_snowflake_parity_evidence.py",
    "classify_semantic_change.py",
    "collect_query_history.py",
    "compile_semantic_manifest.py",
    "evaluate_optimization_experiment.py",
    "excel_xmla_runner.ps1",
    "execute_optimization_diagnostics.py",
    "execute_snowflake_sql.py",
    "export_ossie.py",
    "generate_acceleration_plan.py",
    "generate_ai_integration.py",
    "generate_benchmark_pack.py",
    "generate_microsoft_consumer_pack.py",
    "generate_parity_suite.py",
    "generate_semantic_view.py",
    "ingest_consumer_evidence.py",
    "prepare_powerbi_ingestion.py",
    "render_optimization_experiments.py",
    "report_interchange_compatibility.py",
    "result_signature.py",
    "run_agent_smoke.py",
    "run_snowflake_benchmark.py",
    "semantic_contract.py",
    "smoke_snowflake_mcp.py",
    "validate_parity_evidence.py",
)

REFERENCE_WORKLOAD_EXCLUDED = (
    "benchmark_generation.py",
    "generate_airflow_dag.py",
    "generate_cdc_apply_sql.py",
    "generate_change_events.py",
    "generate_data.py",
    "generate_dbt_project.py",
    "generate_load_sql.py",
    "generate_multi_fact_certification.py",
    "generate_snowflake_ddl.py",
    "materialize_parquet.py",
    "validate_cdc_application.py",
    "validate_cdc_semantic_effects.py",
    "validate_dataset.py",
    "validate_dataset_duckdb.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rewrite_python(text: str) -> str:
    replacements = (
        ("scripts.rga_testbed", "scripts.semantic_platform_core"),
        ('ROOT / "config" / "rga_semantic_contract.yml"', 'ROOT / "config" / "semantic_contract.yml"'),
        ('ROOT / "rga-snowflake-data-platform" / "release"', 'ROOT / "release"'),
        ("rga-snowflake-data-platform", "semantic-platform-release"),
        ("RGA_SYNTHETIC_TESTBED", "SEMANTIC_PLATFORM"),
        ("RGA_SEMANTIC_BENCHMARK", "SEMANTIC_PLATFORM_BENCHMARK"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _readme() -> str:
    return """# Governed Semantic Platform Core

This directory is a standalone export of the reusable governed semantic platform.
It intentionally excludes the RGA synthetic reference workload, synthetic-data generator,
CDC fixtures, RGA dbt/load project, and RGA Airflow DAG.

## Canonical contract

`config/semantic_contract.yml` is the single governed business/semantic contract. Build a release with:

```bash
python scripts/semantic_platform_core/build_semantic_release.py \\
  --contract config/semantic_contract.yml \\
  --database <TARGET_DATABASE> \\
  --output release
```

The release compiles the Snowflake Semantic View, Cortex Agent/MCP specifications,
Power BI/Excel governed consumer pack, cross-consumer parity suite, benchmark pack,
physical-acceleration plan, and semantic interchange artifacts.

## Runtime certification

The exported core also contains the reusable Snowflake benchmark, Agent smoke, managed-MCP
remote smoke, Power BI/Excel evidence capture, parity validation, Query History analysis,
optimization diagnostics, before/after optimization evaluator, and consolidated certification report.

This export does not include any source-domain workload generator. Bring your own physical data/dbt
pipeline and canonical contract; use the RGA pack in the source repository only as a reference workload.
"""


def export_core(contract: Path, output: Path) -> dict[str, Any]:
    if not contract.exists():
        raise FileNotFoundError(f"semantic contract not found: {contract}")

    source_dir = ROOT / "scripts" / "rga_testbed"
    missing = [name for name in CORE_FILES if not (source_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            "core source files are missing: " + ", ".join(sorted(missing))
        )

    if output.exists():
        shutil.rmtree(output)
    package_dir = output / "scripts" / "semantic_platform_core"
    config_dir = output / "config"
    package_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    (output / "scripts" / "__init__.py").write_text("\n", encoding="utf-8")
    (package_dir / "__init__.py").write_text(
        '"""Reusable governed semantic platform core."""\n',
        encoding="utf-8",
    )

    copied: list[dict[str, Any]] = []
    for name in CORE_FILES:
        source = source_dir / name
        target = package_dir / name
        text = source.read_text(encoding="utf-8")
        if source.suffix == ".py":
            text = _rewrite_python(text)
        target.write_text(text, encoding="utf-8")
        copied.append(
            {
                "path": target.relative_to(output).as_posix(),
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
            }
        )

    target_contract = config_dir / "semantic_contract.yml"
    shutil.copyfile(contract, target_contract)
    readme = output / "README.md"
    readme.write_text(_readme(), encoding="utf-8")

    forbidden_paths = [
        output / "scripts" / "semantic_platform_core" / name
        for name in REFERENCE_WORKLOAD_EXCLUDED
    ]
    leaked = [path.name for path in forbidden_paths if path.exists()]
    if leaked:
        raise RuntimeError(
            "reference-workload files leaked into semantic core export: "
            + ", ".join(sorted(leaked))
        )

    python_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in package_dir.glob("*.py")
    )
    forbidden_source_tokens = (
        "scripts.rga_testbed",
        "rga_semantic_contract.yml",
        "RGA_SYNTHETIC_TESTBED",
        "RGA_SEMANTIC_BENCHMARK",
    )
    leaked_tokens = [token for token in forbidden_source_tokens if token in python_text]
    if leaked_tokens:
        raise RuntimeError(
            "RGA-specific defaults leaked into standalone semantic core: "
            + ", ".join(leaked_tokens)
        )

    manifest = {
        "export_version": 1,
        "product_scope": "governed_semantic_platform",
        "reference_workload_included": False,
        "canonical_contract": "config/semantic_contract.yml",
        "canonical_contract_sha256": sha256(target_contract),
        "core_file_count": len(copied),
        "core_files": copied,
        "reference_workload_excluded": list(REFERENCE_WORKLOAD_EXCLUDED),
        "truth_boundary": (
            "This export contains the reusable semantic compiler, governed consumer/runtime evidence, "
            "parity, certification, and optimization tooling. It intentionally excludes the RGA "
            "synthetic-data/CDC/dbt/load/Airflow reference workload and does not provide target-account credentials."
        ),
    }
    manifest_path = output / "core_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "PASS",
        "output": str(output),
        "manifest": str(manifest_path),
        "core_file_count": len(copied),
        "reference_workload_included": False,
    }


def main() -> int:
    args = parse_args()
    try:
        result = export_core(args.contract, args.output)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
