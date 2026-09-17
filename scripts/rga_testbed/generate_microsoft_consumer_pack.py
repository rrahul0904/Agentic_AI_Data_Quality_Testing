#!/usr/bin/env python3
"""Generate Power BI and Excel consumer-validation artifacts for the governed RGA Semantic View.

The live XMLA endpoint is intentionally treated as an external feature gate. This generator
never claims that the endpoint exists in the target Snowflake account.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "microsoft"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def build_contract(database: str) -> dict:
    semantic_view = f"{database}.SEMANTIC.RGA_REINSURANCE_PERFORMANCE"
    return {
        "governance_contract": "one Snowflake Semantic View; no duplicated business metrics in Microsoft clients",
        "semantic_view": semantic_view,
        "protocol": "XMLA",
        "provider": "Snowflake Semantic Views XMLA Endpoint powered by AtScale",
        "availability": "private_preview_feature_gate",
        "power_bi": {
            "required_connection_mode": "live",
            "query_language": "DAX/XMLA",
            "must_not_reimplement": ["CEDED_LOSS_RATIO", "CEDED_PREMIUM_RATE"],
        },
        "excel": {
            "required_connection_mode": "live_xmla",
            "query_language": "MDX/XMLA",
            "must_not_reimplement": ["CEDED_LOSS_RATIO", "CEDED_PREMIUM_RATE"],
        },
        "parity_metrics": [
            "TOTAL_GROSS_PREMIUM",
            "TOTAL_CEDED_PREMIUM",
            "TOTAL_GROSS_CLAIMS",
            "TOTAL_CEDED_CLAIMS",
            "TOTAL_EXPOSURE",
            "TOTAL_CLAIM_COUNT",
            "CEDED_LOSS_RATIO",
            "CEDED_PREMIUM_RATE",
        ],
        "parity_slices": [
            ["CEDANT_NAME", "PERIOD_MONTH"],
            ["TREATY_NAME"],
            ["TREATY_TYPE", "PERIOD_MONTH"],
        ],
        "fallback_policy": (
            "Direct Snowflake connections may be used for connectivity testing, but they are not certified as semantic parity "
            "unless the client consumes the governed Semantic View through the XMLA endpoint."
        ),
    }


def setup_template(database: str) -> str:
    return f"""-- FEATURE GATE: execute only after the Snowflake Semantic Views XMLA Endpoint
-- powered by AtScale is enabled in the target account. Keep this as a template until then.
-- Replace <XMLA_ENDPOINT_NAME> with the endpoint name approved for the environment.

CREATE XMLA ENDPOINT <XMLA_ENDPOINT_NAME>;
ALTER XMLA ENDPOINT <XMLA_ENDPOINT_NAME>
  ADD SEMANTIC VIEW {database}.SEMANTIC.RGA_REINSURANCE_PERFORMANCE;
"""


def checklist(database: str) -> str:
    return f"""# Microsoft Consumer Parity Checklist

Governing object: `{database}.SEMANTIC.RGA_REINSURANCE_PERFORMANCE`

## Power BI

- Confirm the XMLA endpoint is enabled for the Snowflake account.
- Connect using the endpoint URL and verify Power BI reports **Live Connection**.
- Confirm the governed metrics are visible without recreating DAX measures for loss ratio or cession rate.
- Validate ceded loss ratio by cedant/month against the Snowflake Semantic View query.
- Validate ceded premium by treaty against the Snowflake Semantic View query.
- Record screenshots/exported result evidence and the Snowflake query IDs for the parity run.

## Excel

- Connect Excel to the same XMLA endpoint.
- Build a PivotTable using the governed semantic model.
- Confirm the governed loss-ratio and premium measures are available without spreadsheet formulas that redefine them.
- Validate the same cedant/month and treaty slices used by Power BI.
- Record workbook/pivot evidence and the Snowflake query IDs for the parity run.

## Acceptance rule

Power BI, Excel, Snowflake SQL, and AI pass semantic parity only when the same governed metric returns the same value at the same dimensional grain and security context. Direct-connection fallback is connectivity evidence, not semantic-parity certification.
"""


def generate(output: Path, database: str) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    contract_path = output / "consumer_contract.json"
    setup_path = output / "xmla_setup.template.sql"
    checklist_path = output / "PARITY_CHECKLIST.md"
    contract_path.write_text(json.dumps(build_contract(database), indent=2) + "\n", encoding="utf-8")
    setup_path.write_text(setup_template(database), encoding="utf-8")
    checklist_path.write_text(checklist(database), encoding="utf-8")
    return [contract_path, setup_path, checklist_path]


def main() -> int:
    args = parse_args()
    for path in generate(args.output, args.database):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
