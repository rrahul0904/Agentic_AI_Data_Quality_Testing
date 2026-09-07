#!/usr/bin/env python3
"""Reproduces the "Revenue Quality Certification" demo scenario end to end
against a running ADE backend (see revenue_demo/README.md):

  1. Provision a fresh local dbt project (DuckDB).
  2. Install the revenue_demo/ seed + models (with the injected defect).
  3. dbt build.
  4. Register the business concept, contract, and quality rules.
  5. Execute every rule; certify int_revenue and fact_revenue -> expect FAILED.
  6. Run evidence-grounded RCA on fact_revenue -> expect it to localize the
     defect to int_revenue.
  7. Propose, approve, and apply the one-line remediation.
  8. dbt build again; re-execute the rules; re-certify -> expect CERTIFIED.

Usage:
    python3 scripts/run_revenue_demo.py [--base-url http://127.0.0.1:8000]

Requires the ADE backend already running (scripts/run_backend.sh) and the
project's own dbt/venv toolchain already set up (scripts/setup_backend_venv.sh).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

PLATFORM_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = PLATFORM_DIR / "revenue_demo"


def _poll_until_ready(base_url: str, project_id: str, kind: str) -> dict:
    path = "dbt-projects" if kind == "dbt" else "airflow-projects"
    for _ in range(60):
        resp = requests.get(f"{base_url}/api/{path}/{project_id}")
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "PROVISIONING":
            return data
        time.sleep(3)
    raise TimeoutError(f"{kind} project {project_id} did not leave PROVISIONING in time")


def install_demo_models(project: dict) -> None:
    project_dir = Path(project["project_dir"])
    example_dir = project_dir / "models" / "example"
    if example_dir.exists():
        shutil.rmtree(example_dir)
    for sub in ("staging", "intermediate", "marts"):
        (project_dir / "models" / sub).mkdir(parents=True, exist_ok=True)

    shutil.copy(DEMO_DIR / "seeds" / "raw_orders.csv", project_dir / "seeds" / "raw_orders.csv")
    shutil.copy(
        DEMO_DIR / "models" / "staging" / "stg_orders.sql",
        project_dir / "models" / "staging" / "stg_orders.sql",
    )
    shutil.copy(
        DEMO_DIR / "models" / "intermediate" / "int_revenue.sql",
        project_dir / "models" / "intermediate" / "int_revenue.sql",
    )
    shutil.copy(
        DEMO_DIR / "models" / "marts" / "fact_revenue.sql",
        project_dir / "models" / "marts" / "fact_revenue.sql",
    )
    print(f"  installed demo seed + models into {project_dir}")


def dbt_build(project: dict) -> None:
    dbt_bin = str(Path(project["venv_path"]) / "bin" / "dbt")
    cmd = [
        dbt_bin, "build",
        "--project-dir", project["project_dir"],
        "--profiles-dir", project["profiles_dir"],
        "--target", "dev",
        "--no-use-colors",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=project["project_dir"])
    print(result.stdout[-1500:])
    if result.returncode not in (0, 1):  # dbt returns 1 on test failures, which is fine here
        print(result.stderr[-1500:])
        raise RuntimeError(f"dbt build failed unexpectedly (exit {result.returncode})")


def register_rules(base_url: str, project_id: str) -> dict[str, str]:
    bc = requests.post(
        f"{base_url}/api/business-concepts",
        json={
            "name": f"Net Revenue ({project_id[:8]})",
            "domain": "finance",
            "definition": (
                "Gross sales minus discounts, refunds and taxes. Cancelled orders must not contribute "
                "revenue. COMPLETE and SHIPPED orders are recognized. Source and target must reconcile."
            ),
            "criticality": "TIER_1",
            "owner": "finance-data-eng",
        },
    ).json()

    qc = requests.post(
        f"{base_url}/api/quality-contracts",
        json={
            "business_concept_id": bc["id"],
            "dataset_ref": "fact_revenue",
            "sla_ready_by": "06:00",
            "tolerance_percentage": 0.1,
            "owner": "finance-data-eng",
        },
    ).json()

    rule_defs = json.loads((DEMO_DIR / "quality_rules.json").read_text())
    rule_ids: dict[str, str] = {}
    for rule_def in rule_defs:
        use_contract = rule_def.pop("use_contract", False)
        payload = {**rule_def, "dbt_project_id": project_id}
        if use_contract:
            payload["contract_id"] = qc["id"]
        resp = requests.post(f"{base_url}/api/quality-rules", json=payload)
        resp.raise_for_status()
        rule_ids[rule_def["name"]] = resp.json()["id"]
    return rule_ids


def execute_rules(base_url: str, rule_ids: dict[str, str]) -> dict[str, dict]:
    results = {}
    for name, rule_id in rule_ids.items():
        resp = requests.post(f"{base_url}/api/quality-rules/{rule_id}/execute")
        resp.raise_for_status()
        results[name] = resp.json()
        r = results[name]
        print(f"    {name:38s} {r['status']:6s} measured={r['measured_value']}")
    return results


def certify(base_url: str, dataset_ref: str, project_id: str, contract_id: str | None = None) -> dict:
    params = {"dataset_ref": dataset_ref, "dbt_project_id": project_id}
    if contract_id:
        params["contract_id"] = contract_id
    resp = requests.post(f"{base_url}/api/certifications/evaluate", params=params)
    resp.raise_for_status()
    data = resp.json()
    print(f"    {dataset_ref:20s} {data['status']:10s} {data['reason']}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    print("== 1. Provisioning a fresh local DuckDB dbt project ==")
    resp = requests.post(
        f"{base_url}/api/dbt-projects",
        json={"name": f"Revenue Pipeline Demo {int(time.time())}", "execution_mode": "local", "adapter": "duckdb"},
    )
    resp.raise_for_status()
    project_id = resp.json()["id"]
    project = _poll_until_ready(base_url, project_id, "dbt")
    if project["status"] != "READY":
        sys.exit(f"provisioning failed: {project.get('error_message')}")
    print(f"  project_id={project_id}")

    print("== 2. Installing revenue_demo/ seed + models (defect included) ==")
    install_demo_models(project)

    print("== 3. dbt build (first pass -- defect active) ==")
    dbt_build(project)

    print("== 3b. Refreshing lineage against the real models ==")
    requests.post(f"{base_url}/api/dbt-projects/{project_id}/lineage/refresh").raise_for_status()

    print("== 4. Registering business concept, contract, and quality rules ==")
    rule_ids = register_rules(base_url, project_id)

    print("== 5. Executing rules (expect 3 FAILs: row coverage, net/gross revenue reconciliation) ==")
    execute_rules(base_url, rule_ids)

    print("== 6. Certifying (expect FAILED) ==")
    certify(base_url, "int_revenue", project_id)
    cert = certify(base_url, "fact_revenue", project_id)
    assert cert["status"] == "FAILED", f"expected FAILED, got {cert['status']}"

    print("== 7. Evidence-grounded RCA on fact_revenue ==")
    rca_resp = requests.post(
        f"{base_url}/api/rca", params={"dbt_project_id": project_id, "dataset_ref": "fact_revenue"}
    )
    rca_resp.raise_for_status()
    claim = rca_resp.json()
    print(f"    [{claim['status']}] {claim['statement']}")
    assert claim["status"] == "SUPPORTED", f"expected a SUPPORTED claim, got {claim['status']}"

    print("== 8. Proposing, approving, and applying the remediation ==")
    prop = requests.post(
        f"{base_url}/api/remediation-proposals",
        json={
            "claim_id": claim["id"],
            "target_file": "models/intermediate/int_revenue.sql",
            "find_text": "where status = 'COMPLETE'",
            "replace_text": "where status in ('COMPLETE', 'SHIPPED')",
        },
    ).json()
    requests.post(f"{base_url}/api/remediation-proposals/{prop['id']}/approve").raise_for_status()
    requests.post(f"{base_url}/api/remediation-proposals/{prop['id']}/apply").raise_for_status()
    print(f"    applied proposal {prop['id']}")

    print("== 9. dbt build (second pass -- fix applied) ==")
    dbt_build(project)

    print("== 10. Re-executing rules (expect all PASS) ==")
    results = execute_rules(base_url, rule_ids)
    assert all(r["status"] == "PASS" for r in results.values()), "expected every rule to pass after the fix"

    print("== 11. Re-certifying (expect CERTIFIED) ==")
    certify(base_url, "int_revenue", project_id)
    cert = certify(base_url, "fact_revenue", project_id)
    assert cert["status"] == "CERTIFIED", f"expected CERTIFIED, got {cert['status']}"

    print("\n✅ Revenue Quality Certification demo scenario completed end to end.")
    print(f"   dbt_project_id={project_id}")


if __name__ == "__main__":
    main()
