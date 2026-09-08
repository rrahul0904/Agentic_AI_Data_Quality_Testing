"""User-facing `agentic` entrypoint: CLI subcommands or interactive TUI."""

from __future__ import annotations

import json
import sys

from agentic_data_platform import cli
from agentic_data_platform.interface import AgenticService
from agentic_data_platform.tui.app import main as tui_main


CLI_COMMANDS = {
    "discover", "doctor", "tool", "dbt", "airflow", "platform", "reconcile",
    "sql", "lineage", "schema", "warehouse", "diff", "quality", "dbt-run",
    "review", "connection", "metadata", "data-diff", "finops", "governance",
    "provider", "mcp", "skill", "training", "session", "memory", "trace", "job",
    "plan-migration", "verify", "approve", "execute", "sessions",
}


def main() -> int:
    argv = sys.argv[1:]
    first = next((item for item in argv if not item.startswith("-")), None)
    if first == "sessions":
        service = AgenticService(".")
        operation = argv[1] if len(argv) > 1 else "list"
        if operation == "list":
            payload = {"sessions": service.sessions()}
        elif operation == "show" and len(argv) > 2:
            payload = service.session_replay(argv[2])
        else:
            raise SystemExit("usage: agentic sessions list | agentic sessions show <id>")
        print(json.dumps(payload, indent=2, default=str))
        return 0
    if first == "trace" and len(argv) > 1 and argv[1] not in {"list", "show", "export", "replay"}:
        service = AgenticService(".")
        print(json.dumps(service.replay_trace(argv[1]), indent=2, default=str))
        return 0
    if first in CLI_COMMANDS or "--json" in argv:
        return cli.main(argv)
    return tui_main(argv)
