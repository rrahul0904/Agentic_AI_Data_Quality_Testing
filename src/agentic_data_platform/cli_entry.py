"""Compatibility entrypoint that extends the canonical ADE CLI without rewriting it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from agentic_data_platform.cli import main as canonical_main
from agentic_data_platform.errors import safe_error
from agentic_data_platform.runtime.local_agent import (
    index_project_knowledge,
    ingest_document,
    knowledge_search,
    knowledge_status,
    run_project_agent,
)
from agentic_data_platform.tools.builtin import build_tool_registry


def _default_project() -> str:
    cwd = Path.cwd()
    hospitality = cwd / "hospitality-snowflake-data-platform"
    return str(hospitality if hospitality.is_dir() else cwd)


def _emit(payload: object) -> int:
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _ask(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ade ask", description="Ask the project-aware governed agent")
    parser.add_argument("question")
    parser.add_argument("--project", default=_default_project())
    parser.add_argument("--provider")
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    return _emit(
        run_project_agent(
            build_tool_registry(),
            args.project,
            args.question,
            provider=args.provider,
            model=args.model,
        )
    )


def _knowledge(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ade knowledge", description="Manage local project knowledge")
    parser.add_argument("operation", choices=["index", "ingest", "search", "status"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--project", default=_default_project())
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)

    if args.operation == "index":
        payload = index_project_knowledge(args.project)
    elif args.operation == "status":
        payload = knowledge_status(args.project)
    elif args.operation == "search":
        if not args.value:
            raise ValueError("knowledge search requires a query")
        payload = knowledge_search(args.project, args.value, limit=max(1, min(args.limit, 100)))
    else:
        if not args.value:
            raise ValueError("knowledge ingest requires a file path")
        path = Path(args.value).expanduser().resolve()
        payload = ingest_document(args.project, path.name, path.read_bytes())
    return _emit(payload)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args and args[0] == "ask":
            return _ask(args[1:])
        if args and args[0] == "knowledge":
            return _knowledge(args[1:])
        return canonical_main(args)
    except (FileNotFoundError, KeyError, OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": safe_error(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
