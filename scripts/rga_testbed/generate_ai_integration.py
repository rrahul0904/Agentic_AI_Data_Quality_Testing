#!/usr/bin/env python3
"""Generate governed Snowflake Cortex Agent and managed MCP contracts from one semantic contract."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, ai_object_names, domain_guidance, load_semantic_contract, semantic_view_fqn
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, ai_object_names, domain_guidance, load_semantic_contract, semantic_view_fqn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "ai"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def build_agent_spec(database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict:
    contract = load_semantic_contract(contract_path, database)
    names = ai_object_names(contract)
    guidance = domain_guidance(contract)
    tool_name = names["tool_name"]
    return {
        "models": {"orchestration": "auto"},
        "orchestration": {
            "capabilities": {"analytical_search": True},
            "budget": {"seconds": 30, "tokens": 16000},
        },
        "instructions": {
            "response": guidance["agent_response"],
            "orchestration": guidance["agent_orchestration"],
            "sample_questions": [{"question": item["question"]} for item in contract["verified_queries"]],
        },
        "tools": [
            {
                "tool_spec": {
                    "type": contract["consumers"]["ai"]["tool_type"],
                    "name": tool_name,
                    "description": guidance["tool_description"],
                }
            }
        ],
        "tool_resources": {
            tool_name: {"semantic_view": semantic_view_fqn(contract)}
        },
    }


def build_mcp_spec(database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict:
    contract = load_semantic_contract(contract_path, database)
    if contract["consumers"]["ai"]["allow_unrestricted_sql"]:
        raise ValueError("Canonical semantic contract does not permit unrestricted SQL")
    names = ai_object_names(contract)
    guidance = domain_guidance(contract)
    return {
        "tools": [
            {
                "title": names["tool_title"],
                "name": names["tool_name"].lower(),
                "type": "CORTEX_AGENT_RUN",
                "identifier": f"{database}.AI.{names['agent_name']}",
                "description": guidance["mcp_description"],
            }
        ]
    }


def render_create_agent(database: str, spec: dict, contract: dict) -> str:
    yaml_text = yaml.safe_dump(spec, sort_keys=False, width=120)
    names = ai_object_names(contract)
    comment = str(contract.get("description") or contract["name"]).replace("'", "''")
    return (
        f"CREATE OR REPLACE AGENT {database}.AI.{names['agent_name']}\n"
        f"  COMMENT = 'Governed agent over {comment}'\n"
        "  FROM SPECIFICATION\n"
        "  $\n"
        f"{yaml_text.rstrip()}\n"
        "  $;\n"
    )


def render_create_mcp(database: str, spec: dict, contract: dict) -> str:
    yaml_text = yaml.safe_dump(spec, sort_keys=False, width=120)
    names = ai_object_names(contract)
    return (
        f"CREATE OR REPLACE MCP SERVER {database}.AI.{names['mcp_name']}\n"
        "  FROM SPECIFICATION $\n"
        f"{yaml_text.rstrip()}\n"
        "  $;\n"
    )


def generate(output: Path, database: str, contract_path: Path = DEFAULT_CONTRACT) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    contract = load_semantic_contract(contract_path, database)
    agent_spec = build_agent_spec(database, contract_path)
    mcp_spec = build_mcp_spec(database, contract_path)
    files = [
        (output / "agent_spec.yml", yaml.safe_dump(agent_spec, sort_keys=False, width=120)),
        (output / "mcp_spec.yml", yaml.safe_dump(mcp_spec, sort_keys=False, width=120)),
        (output / "create_agent.sql", render_create_agent(database, agent_spec, contract)),
        (output / "create_mcp_server.sql", render_create_mcp(database, mcp_spec, contract)),
    ]
    for path, text in files:
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return [path for path, _ in files]


def main() -> int:
    args = parse_args()
    for path in generate(args.output, args.database, args.contract):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
