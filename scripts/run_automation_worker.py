#!/usr/bin/env python3
"""Run persistent ADE automations as a one-shot or unattended worker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import time

from agentic_data_platform.automations import AutomationService
from agentic_data_platform.tools.builtin import build_tool_registry


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run due Agentic Data Engineering OS automations")
    value.add_argument("--project", default=".", help="ADE project root")
    value.add_argument("--database", help="automation SQLite database; defaults to PROJECT/.ade/automations.db")
    value.add_argument("--poll-seconds", type=float, default=30.0)
    value.add_argument("--limit", type=int, default=100)
    value.add_argument("--once", action="store_true", help="run due schedules once and exit")
    value.add_argument("--json", action="store_true", help="emit machine-readable JSON per poll")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    database = Path(args.database).expanduser().resolve() if args.database else project / ".ade" / "automations.db"
    if args.poll_seconds < 1:
        raise SystemExit("--poll-seconds must be >= 1")
    if args.limit < 1:
        raise SystemExit("--limit must be >= 1")

    service = AutomationService(database)
    registry = build_tool_registry()
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while not stopping:
        result = service.run_due(registry, limit=args.limit)
        payload = {
            "status": result["status"],
            "database": str(database),
            "project": str(project),
            **result,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True, default=str), flush=True)
        elif result["run_count"]:
            print(
                f"ADE automations: {result['run_count']} run(s), "
                f"{result['failed_count']} failed, {result['blocked_count']} blocked",
                flush=True,
            )

        if args.once:
            return 1 if result["status"] == "FAIL" else 0
        time.sleep(args.poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
