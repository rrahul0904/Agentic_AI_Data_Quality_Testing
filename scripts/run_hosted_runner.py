#!/usr/bin/env python3
"""Hostable ADE runner worker process."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import socket
import time

from agentic_data_platform.runners import HostedRunnerStore
from agentic_data_platform.tools.builtin import build_tool_registry


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run a hostable ADE worker")
    value.add_argument("--project", default=".")
    value.add_argument("--database")
    value.add_argument("--runner-id")
    value.add_argument("--name", default=socket.gethostname())
    value.add_argument("--capability", action="append", default=[])
    value.add_argument("--poll-seconds", type=float, default=5)
    value.add_argument("--lease-seconds", type=int, default=120)
    value.add_argument("--once", action="store_true")
    value.add_argument("--json", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    database = Path(args.database).expanduser().resolve() if args.database else project / ".ade" / "hosted-runner.db"
    store = HostedRunnerStore(database)
    runner = store.register_runner(
        name=args.name,
        capabilities=args.capability or ["*"],
        runner_id=args.runner_id,
        metadata={"project": str(project)},
    )
    registry = build_tool_registry()
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while not stopping:
        result = store.run_once(registry, runner["runner_id"], lease_seconds=args.lease_seconds)
        if args.json:
            print(json.dumps(result, sort_keys=True, default=str), flush=True)
        elif result.get("status") != "IDLE":
            print(f"ADE hosted runner {runner['runner_id']}: {result.get('status')}", flush=True)
        if args.once:
            return 1 if result.get("status") == "FAIL" else 0
        time.sleep(max(1.0, args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
