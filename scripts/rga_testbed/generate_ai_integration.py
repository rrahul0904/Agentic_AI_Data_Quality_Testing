#!/usr/bin/env python3
"""Generate Snowflake Cortex Agent and managed MCP server contracts for RGA analytics."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "ai"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def build_agent_spec(database: str) -> dict:
    return {
        "models": {"orchestration": "auto"},
        "orchestration": {
            "capabilities": {"analytical_search": True},
            "budget": {"seconds": 30, "tokens": 16000},
        },
        "instructions": {
            "response": (
                "Answer concisely using only governed synthetic reinsurance analytics. "
                "Clearly state that the dataset is synthetic when that context matters."
            ),
            "orchestration": (
                "Use Reinsurance_Analyst for questions about cedants, treaties, premiums, claims, exposure, "
                "loss ratios, cession rates, and monthly reinsurance performance. Do not invent measures."
            ),
            "sample_questions": [
                {"question": "What is the monthly ceded loss ratio by cedant?"},
                {"question": "Which treaties have the highest ceded premium?"},
                {"question": "How are ceded claims and exposure trending by month?"},
            ],
        },
        "tools": [
            {
                "tool_spec": {
                    "type": "cortex_analyst_text_to_sql",
                    "name": "Reinsurance_Analyst",
                    "description": "Answers governed Life & Health reinsurance analytics questions using the RGA semantic view.",
                }
            }
        ],
        "tool_resources": {
            "Reinsurance_Analyst": {
                "semantic_view": f"{database}.SEMANTIC.RGA_REINSURANCE_PERFORMANCE"
            }
        },
    }


def build_mcp_spec(database: str) -> dict:
    return {
        "tools": [
            {
                "title": "Governed RGA Reinsurance Analytics Agent",
                "name": "rga_reinsurance_agent",
                "type": "CORTEX_AGENT_RUN",
                "identifier": f"{database}.AI.RGA_REINSURANCE_AGENT",
                "description": (
                    "Use this agent for governed questions about the synthetic Life & Health reinsurance dataset, "
                    "including premiums, claims, exposure, treaties, cedants, loss ratios, and cession metrics."
                ),
            }
        ]
    }


def render_create_agent(database: str, spec: dict) -> str:
    yaml_text = yaml.safe_dump(spec, sort_keys=False, width=120)
    return (
        f"CREATE OR REPLACE AGENT {database}.AI.RGA_REINSURANCE_AGENT\n"
        "  COMMENT = 'Governed agent over the synthetic RGA reinsurance Semantic View'\n"
        "  FROM SPECIFICATION\n"
        "  $$\n"
        f"{yaml_text.rstrip()}\n"
        "  $$;\n"
    )


def render_create_mcp(database: str, spec: dict) -> str:
    yaml_text = yaml.safe_dump(spec, sort_keys=False, width=120)
    return (
        f"CREATE OR REPLACE MCP SERVER {database}.AI.RGA_REINSURANCE_MCP\n"
        "  FROM SPECIFICATION $$\n"
        f"{yaml_text.rstrip()}\n"
        "  $$;\n"
    )


def generate(output: Path, database: str) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    agent_spec = build_agent_spec(database)
    mcp_spec = build_mcp_spec(database)
    files = [
        (output / "agent_spec.yml", yaml.safe_dump(agent_spec, sort_keys=False, width=120)),
        (output / "mcp_spec.yml", yaml.safe_dump(mcp_spec, sort_keys=False, width=120)),
        (output / "create_agent.sql", render_create_agent(database, agent_spec)),
        (output / "create_mcp_server.sql", render_create_mcp(database, mcp_spec)),
    ]
    for path, content in files:
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return [path for path, _ in files]


def main() -> int:
    args = parse_args()
    for path in generate(args.output, args.database):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
