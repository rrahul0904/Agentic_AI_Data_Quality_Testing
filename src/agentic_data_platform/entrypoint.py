"""User-facing `agentic` entrypoint: CLI subcommands or interactive TUI."""

from __future__ import annotations

import sys

from agentic_data_platform import cli
from agentic_data_platform.tui.app import main as tui_main


CLI_COMMANDS = {
    "discover", "doctor", "tool", "dbt", "airflow", "platform", "reconcile",
    "sql", "lineage", "schema", "warehouse", "diff", "quality", "dbt-run",
    "review", "connection", "metadata", "data-diff", "finops", "governance",
    "provider", "mcp", "skill", "training", "session", "memory", "trace", "job",
    "plan-migration", "verify", "approve", "execute",
}


def main() -> int:
    argv = sys.argv[1:]
    first = next((item for item in argv if not item.startswith("-")), None)
    if first in CLI_COMMANDS or "--json" in argv:
        return cli.main(argv)
    return tui_main(argv)
