"""Compatibility entrypoint that extends the canonical ADE CLI without rewriting it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys

from agentic_data_platform.cli import main as canonical_main
from agentic_data_platform.compute import ComputeJobSpec, PortableComputePlanner
from agentic_data_platform.errors import safe_error
from agentic_data_platform.knowledge import local_document_intelligence, snowflake_parse_document_sql
from agentic_data_platform.remote_workspace import RemoteWorkspaceConfig, SSHRemoteWorkspace
from agentic_data_platform.retrieval import LocalProjectRetrievalBackend, RetrievalQuery
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


def _retrieval(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ade retrieval", description="Search governed project retrieval backends")
    parser.add_argument("operation", choices=["local"])
    parser.add_argument("query")
    parser.add_argument("--project", default=_default_project())
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    backend = LocalProjectRetrievalBackend(args.project)
    hits = backend.search(RetrievalQuery(args.query, limit=args.limit))
    return _emit({"status": "PASS", "backend": backend.name, "results": [hit.as_dict() for hit in hits]})


def _document(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ade document", description="Document-intelligence workflows")
    sub = parser.add_subparsers(dest="operation", required=True)
    local = sub.add_parser("extract", help="deterministically extract local document content")
    local.add_argument("path")
    snowflake = sub.add_parser("snowflake-plan", help="render Snowflake AI_PARSE_DOCUMENT SQL")
    snowflake.add_argument("--stage", required=True)
    snowflake.add_argument("--path", required=True)
    snowflake.add_argument("--mode", choices=["OCR", "LAYOUT"], default="LAYOUT")
    snowflake.add_argument("--no-page-split", action="store_true")
    snowflake.add_argument("--extract-images", action="store_true")
    args = parser.parse_args(argv)
    if args.operation == "extract":
        path = Path(args.path).expanduser().resolve()
        return _emit(local_document_intelligence(path.name, path.read_bytes()))
    return _emit(
        {
            "status": "PLAN",
            "backend": "snowflake_ai_parse_document",
            "sql": snowflake_parse_document_sql(
                args.stage,
                args.path,
                mode=args.mode,
                page_split=not args.no_page_split,
                extract_images=args.extract_images,
            ),
        }
    )


def _compute(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ade compute", description="Plan portable Docker/Kubernetes/Snowflake compute")
    parser.add_argument("operation", choices=["plan"])
    parser.add_argument("--backend", required=True, choices=["docker", "kubernetes", "snowflake-spcs"])
    parser.add_argument("--name", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--command", default="")
    parser.add_argument("--cpu", type=float, default=1.0)
    parser.add_argument("--memory-gib", type=float, default=2.0)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--workspace")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--compute-pool")
    parser.add_argument("--query-warehouse")
    args = parser.parse_args(argv)
    spec = ComputeJobSpec(
        name=args.name,
        image=args.image,
        command=tuple(shlex.split(args.command)),
        cpu=args.cpu,
        memory_gib=args.memory_gib,
        gpu=args.gpu,
        timeout_seconds=args.timeout,
        network_enabled=args.network,
        workspace=args.workspace,
        replicas=args.replicas,
    )
    planner = PortableComputePlanner()
    if args.backend == "docker":
        plan = planner.docker(spec)
    elif args.backend == "kubernetes":
        plan = planner.kubernetes(spec, namespace=args.namespace)
    else:
        if not args.compute_pool:
            raise ValueError("--compute-pool is required for snowflake-spcs")
        plan = planner.snowflake_spcs(
            spec,
            compute_pool=args.compute_pool,
            query_warehouse=args.query_warehouse,
        )
    return _emit({"status": "PLAN", **plan.as_dict()})


def _remote(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ade remote", description="Governed SSH remote workspace")
    parser.add_argument("operation", choices=["status", "list", "read", "write", "run"])
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--identity-file")
    parser.add_argument("--path", default=".")
    parser.add_argument("--content")
    parser.add_argument("--command")
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args(argv)
    workspace = SSHRemoteWorkspace(
        RemoteWorkspaceConfig(
            host=args.host,
            user=args.user,
            root=args.root,
            port=args.port,
            identity_file=args.identity_file,
        )
    )
    if args.operation == "status":
        payload = workspace.status()
    elif args.operation == "list":
        payload = workspace.list_files(args.path)
    elif args.operation == "read":
        payload = workspace.read_text(args.path)
    elif args.operation == "write":
        if args.content is None:
            raise ValueError("remote write requires --content")
        payload = workspace.write_text(args.path, args.content, approved=args.approved)
    else:
        if not args.command:
            raise ValueError("remote run requires --command")
        payload = workspace.run(
            shlex.split(args.command),
            cwd=args.path,
            approved=args.approved,
            read_only=args.read_only,
        )
    return _emit(payload)


def _acp(argv: list[str]) -> int:
    if not argv or argv[0] != "serve":
        raise ValueError("usage: ade acp serve [--provider NAME] [--model NAME]")
    from agentic_data_platform.acp_server import main as acp_main

    return acp_main(argv[1:])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args and args[0] == "ask":
            return _ask(args[1:])
        if args and args[0] == "knowledge":
            return _knowledge(args[1:])
        if args and args[0] == "retrieval":
            return _retrieval(args[1:])
        if args and args[0] == "document":
            return _document(args[1:])
        if args and args[0] == "compute":
            return _compute(args[1:])
        if args and args[0] == "remote":
            return _remote(args[1:])
        if args and args[0] == "acp":
            return _acp(args[1:])
        return canonical_main(args)
    except (FileNotFoundError, KeyError, OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": safe_error(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
