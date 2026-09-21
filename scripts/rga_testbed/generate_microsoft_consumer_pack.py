#!/usr/bin/env python3
"""Generate Power BI and Excel validation artifacts from the canonical semantic contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, metric_names, semantic_view_fqn
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, metric_names, semantic_view_fqn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "microsoft"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def build_contract(database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict:
    contract = load_semantic_contract(contract_path, database)
    pbi = contract["consumers"]["power_bi"]
    excel = contract["consumers"]["excel"]
    parity_slices = [query.get("dimensions", []) for query in contract["verified_queries"]]
    derived = [
        metric["name"]
        for metric in contract["metrics"]
        if "/" in metric["expr"] or "NULLIF" in metric["expr"].upper()
    ]
    return {
        "governance_contract": "one canonical semantic contract; no duplicated business metrics in Microsoft clients",
        "semantic_view": semantic_view_fqn(contract),
        "protocol": pbi["protocol"],
        "provider": "Snowflake Semantic Views XMLA Endpoint powered by AtScale",
        "availability": "account_entitlement_or_feature_gate_required",
        "availability_policy": (
            "Detect endpoint availability in the target Snowflake account. "
            "Do not assume universal availability from repository configuration."
        ),
        "power_bi": {
            "required_connection_mode": pbi["required_connection_mode"],
            "query_language": "DAX/XMLA",
            "must_not_reimplement": derived,
            "parity_evidence_paths": [
                "governed_live_xmla",
                "execute_dax_queries_api_when_power_bi_semantic_model_supported",
            ],
            "api_evidence_note": (
                "Execute DAX Queries can automate Power BI result evidence for a "
                "supported Power BI semantic model. It does not certify Excel."
            ),
        },
        "excel": {
            "required_connection_mode": excel["required_connection_mode"],
            "query_language": "MDX/XMLA",
            "must_not_reimplement": derived,
            "parity_evidence_paths": ["governed_excel_xmla_client"],
            "api_evidence_note": (
                "Power BI REST evidence is not Excel evidence; Excel requires its own "
                "governed live/XMLA capture."
            ),
        },
        "parity_metrics": metric_names(contract),
        "parity_slices": parity_slices,
        "fallback_policy": (
            "Direct Snowflake connections may be used for connectivity testing, but they are not certified as semantic parity "
            "unless the client consumes the governed Semantic View through the approved governed path."
        ),
    }


def setup_template(database: str, contract_path: Path = DEFAULT_CONTRACT) -> str:
    contract = load_semantic_contract(contract_path, database)
    return f"""-- FEATURE GATE: execute only after the Snowflake Semantic Views XMLA Endpoint
-- powered by AtScale is enabled in the target account. Keep this as a template until then.
-- Replace <XMLA_ENDPOINT_NAME> with the endpoint name approved for the environment.

CREATE XMLA ENDPOINT <XMLA_ENDPOINT_NAME>;
ALTER XMLA ENDPOINT <XMLA_ENDPOINT_NAME>
  ADD SEMANTIC VIEW {semantic_view_fqn(contract)};
"""


def checklist(database: str, contract_path: Path = DEFAULT_CONTRACT) -> str:
    contract = load_semantic_contract(contract_path, database)
    derived = [
        item["name"]
        for item in contract["metrics"]
        if "/" in item["expr"] or "NULLIF" in item["expr"].upper()
    ]
    forbidden = ", ".join(derived)
    return f"""# Microsoft Consumer Parity Checklist

Governing object: {semantic_view_fqn(contract)}
Canonical source: config/rga_semantic_contract.yml

## Power BI

- Detect whether the governed Snowflake Semantic Views XMLA endpoint is enabled/entitled in the target account; do not assume availability.
- Connect using the endpoint URL and verify Power BI reports Live Connection using the required live connection mode.
- Confirm governed metrics are visible without recreating {forbidden} in DAX.
- Execute every canonical verified-query slice defined in the semantic contract.
- Where an actual Power BI semantic model supports Execute DAX Queries, the generated `.powerbi.dax` files may automate result evidence capture through the Power BI API.
- Power BI API evidence is valid only for that Power BI semantic model and does not certify Excel.
- Record governed result evidence and the relevant platform/query identifiers.

## Excel

- Connect Excel to the same governed semantic endpoint after account capability/entitlement is confirmed.
- Build PivotTables from the governed model.
- Confirm governed metrics are available without spreadsheet formulas that redefine {forbidden}.
- Execute the same canonical verified-query slices used for Snowflake and Power BI.
- Record workbook/pivot evidence and Snowflake query IDs.

## Acceptance rule

Power BI, Excel, Snowflake SQL, and AI pass semantic parity only when the same canonical metric returns the same value at the same dimensional grain and security context. Direct-connection fallback is connectivity evidence, not semantic-parity certification.
"""


def generate(output: Path, database: str, contract_path: Path = DEFAULT_CONTRACT) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    contract_out = output / "consumer_contract.json"
    setup_path = output / "xmla_setup.template.sql"
    checklist_path = output / "PARITY_CHECKLIST.md"
    contract_out.write_text(json.dumps(build_contract(database, contract_path), indent=2) + "\n", encoding="utf-8")
    setup_path.write_text(setup_template(database, contract_path), encoding="utf-8")
    checklist_path.write_text(checklist(database, contract_path), encoding="utf-8")
    return [contract_out, setup_path, checklist_path]


def main() -> int:
    args = parse_args()
    for path in generate(args.output, args.database, args.contract):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
