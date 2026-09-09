"""CoCo-parity coding workspace: explainable code search and governed Python REPL."""

from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

from agentic_data_platform.advanced_capabilities import run_command
from agentic_data_platform.runners import sandbox as sandbox_runner
from agentic_data_platform.workspace_files import workspace_file_glob


_CODE_SUFFIXES = {
    ".py", ".sql", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs",
    ".scala", ".sh", ".bash", ".yml", ".yaml", ".json", ".toml", ".md",
}
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")
_SYMBOL = re.compile(
    r"(?m)^\s*(?:def|class|function|interface|type|struct|enum|macro|model)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _root(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_session_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())[:96]
    if not normalized:
        raise ValueError("session_id is required")
    return normalized


def _subtokens(value: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ").replace("-", " ")
    return [token.casefold() for token in _TOKEN.findall(expanded)]


def _tokens(value: str) -> set[str]:
    return set(_subtokens(value))


def _python_symbols(text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    symbols: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(
                {
                    "name": node.name,
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "line": int(getattr(node, "lineno", 0) or 0),
                    "end_line": int(getattr(node, "end_lineno", 0) or 0),
                    "doc": ast.get_docstring(node) or "",
                }
            )
    return symbols


def _generic_symbols(text: str) -> list[dict[str, Any]]:
    symbols = []
    for match in _SYMBOL.finditer(text):
        symbols.append(
            {
                "name": match.group(1),
                "kind": "symbol",
                "line": text.count("\n", 0, match.start()) + 1,
                "end_line": text.count("\n", 0, match.end()) + 1,
                "doc": "",
            }
        )
    return symbols


def code_index(
    workspace: str | Path,
    *,
    patterns: Iterable[str] | None = None,
    max_file_bytes: int = 1_000_000,
    limit: int = 5000,
) -> dict[str, Any]:
    root = _root(workspace)
    selected_patterns = list(patterns or ["**/*"])
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for pattern in selected_patterns:
        listing = workspace_file_glob(root, pattern, limit=10000)
        for item in listing["files"]:
            if item["path"] in seen or item["size"] > max_file_bytes:
                continue
            suffix = Path(item["path"]).suffix.casefold()
            if suffix not in _CODE_SUFFIXES:
                continue
            seen.add(item["path"])
            target = root / item["path"]
            text = target.read_text(encoding="utf-8", errors="replace")
            symbols = _python_symbols(text) if suffix == ".py" else _generic_symbols(text)
            records.append(
                {
                    "path": item["path"],
                    "suffix": suffix,
                    "sha256": item["sha256"],
                    "size": item["size"],
                    "symbols": symbols,
                    "symbol_names": [symbol["name"] for symbol in symbols],
                    "text": text,
                }
            )
            if len(records) >= max(1, min(int(limit), 20000)):
                break
        if len(records) >= max(1, min(int(limit), 20000)):
            break
    return {
        "status": "PASS",
        "files": records,
        "file_count": len(records),
        "index_fingerprint": _digest(
            [(record["path"], record["sha256"], record["symbol_names"]) for record in records]
        ),
    }


def deterministic_code_search(
    workspace: str | Path,
    query: str,
    *,
    patterns: Iterable[str] | None = None,
    limit: int = 50,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    needle = str(query)
    if not needle.strip():
        raise ValueError("query is required")
    index = code_index(workspace, patterns=patterns)
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(re.escape(needle), flags)
    matches: list[dict[str, Any]] = []
    for record in index["files"]:
        for line_number, line in enumerate(record["text"].splitlines(), start=1):
            match = compiled.search(line)
            if not match:
                continue
            matches.append(
                {
                    "path": record["path"],
                    "line": line_number,
                    "column": match.start() + 1,
                    "text": line[:2000],
                    "file_sha256": record["sha256"],
                    "match_type": "exact_text",
                }
            )
            if len(matches) >= max(1, int(limit)):
                break
        if len(matches) >= max(1, int(limit)):
            break
    return {
        "status": "PASS",
        "backend": "deterministic_text",
        "query": query,
        "matches": matches,
        "count": len(matches),
        "index_fingerprint": index["index_fingerprint"],
        "evidence_fingerprint": _digest(matches),
    }


def semantic_code_search(
    workspace: str | Path,
    query: str,
    *,
    patterns: Iterable[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    query_tokens = _tokens(query)
    if not query_tokens:
        raise ValueError("query is required")
    index = code_index(workspace, patterns=patterns)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for record in index["files"]:
        path_tokens = _tokens(record["path"])
        symbol_tokens = set()
        doc_tokens = set()
        for symbol in record["symbols"]:
            symbol_tokens.update(_tokens(symbol["name"]))
            doc_tokens.update(_tokens(symbol.get("doc") or ""))
        text_tokens = set()
        for token in _TOKEN.findall(record["text"][:20000]):
            text_tokens.update(_subtokens(token))
        all_tokens = path_tokens | symbol_tokens | doc_tokens | text_tokens
        overlap = query_tokens & all_tokens
        if not overlap:
            continue
        exact_symbol = sum(
            1
            for symbol in record["symbol_names"]
            if str(symbol).casefold() in str(query).casefold()
            or str(query).casefold() in str(symbol).casefold()
        )
        symbol_overlap = len(query_tokens & symbol_tokens)
        path_overlap = len(query_tokens & path_tokens)
        doc_overlap = len(query_tokens & doc_tokens)
        jaccard = len(overlap) / max(1, len(query_tokens | all_tokens))
        coverage = len(overlap) / len(query_tokens)
        score = (
            coverage * 6.0
            + symbol_overlap * 2.5
            + exact_symbol * 3.0
            + path_overlap * 1.5
            + doc_overlap * 1.25
            + math.log1p(jaccard * 100)
        )
        matched_symbols = [
            symbol
            for symbol in record["symbols"]
            if query_tokens & _tokens(symbol["name"] + " " + (symbol.get("doc") or ""))
        ][:10]
        ranked.append(
            (
                score,
                {
                    "path": record["path"],
                    "file_sha256": record["sha256"],
                    "score": round(score, 6),
                    "matched_terms": sorted(overlap),
                    "matched_symbols": matched_symbols,
                    "score_components": {
                        "coverage": round(coverage, 6),
                        "symbol_overlap": symbol_overlap,
                        "exact_symbol": exact_symbol,
                        "path_overlap": path_overlap,
                        "doc_overlap": doc_overlap,
                        "jaccard": round(jaccard, 6),
                    },
                },
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1]["path"]))
    results = [item for _, item in ranked[: max(1, int(limit))]]
    return {
        "status": "PASS",
        "backend": "local_structural_semantic",
        "query": query,
        "results": results,
        "count": len(results),
        "index_fingerprint": index["index_fingerprint"],
        "ranking_fingerprint": _digest(results),
        "explainable": True,
    }


def code_search(
    workspace: str | Path,
    query: str,
    *,
    mode: str = "semantic",
    patterns: Iterable[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    key = str(mode).casefold().replace("-", "_")
    if key in {"deterministic", "text", "exact"}:
        return deterministic_code_search(
            workspace,
            query,
            patterns=patterns,
            limit=limit,
        )
    if key in {"semantic", "structural", "local_semantic"}:
        return semantic_code_search(
            workspace,
            query,
            patterns=patterns,
            limit=limit,
        )
    raise ValueError("mode must be deterministic or semantic")


def _repl_paths(workspace: str | Path, session_id: str) -> tuple[Path, Path]:
    root = _root(workspace)
    safe = _safe_session_id(session_id)
    directory = root / ".ade" / "repl"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe}.state.json", directory / f"{safe}.history.jsonl"


def _repl_wrapper(code: str, state_path: str, history_path: str) -> str:
    return f"""
import contextlib
import io
import json
import pathlib
import traceback

state_path = pathlib.Path({state_path!r})
history_path = pathlib.Path({history_path!r})
state = {{}}
if state_path.exists():
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
    except Exception:
        state = {{}}
namespace = dict(state)
stdout = io.StringIO()
stderr = io.StringIO()
status = 'PASS'
error = None
with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
    try:
        exec({code!r}, namespace, namespace)
    except Exception:
        status = 'FAIL'
        error = traceback.format_exc()
serializable = {{}}
for key, value in namespace.items():
    if key.startswith('__'):
        continue
    try:
        json.dumps(value)
    except Exception:
        continue
    serializable[key] = value
if status == 'PASS':
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(serializable, sort_keys=True), encoding='utf-8')
history_path.parent.mkdir(parents=True, exist_ok=True)
with history_path.open('a', encoding='utf-8') as handle:
    handle.write(json.dumps({{'code': {code!r}, 'status': status, 'error': error}}, sort_keys=True) + '\\n')
print(json.dumps({{
    'status': status,
    'stdout': stdout.getvalue(),
    'stderr': stderr.getvalue(),
    'error': error,
    'state': serializable,
}}, sort_keys=True))
""".strip()


def python_repl_plan(
    workspace: str | Path,
    code: str,
    *,
    session_id: str = "default",
    backend: str = "container",
    image: str = "python:3.12-slim",
    timeout_seconds: int = 60,
    memory_mb: int = 512,
    network_enabled: bool = False,
) -> dict[str, Any]:
    if not str(code).strip():
        raise ValueError("code is required")
    key = str(backend).casefold().replace("-", "_")
    if key not in {"container", "local_constrained"}:
        raise ValueError("backend must be container or local_constrained")
    state_path, history_path = _repl_paths(workspace, session_id)
    root = _root(workspace)
    state_rel = state_path.relative_to(root).as_posix()
    history_rel = history_path.relative_to(root).as_posix()
    wrapper = _repl_wrapper(
        str(code),
        f"/workspace/{state_rel}" if key == "container" else str(state_path),
        f"/workspace/{history_rel}" if key == "container" else str(history_path),
    )
    payload = {
        "backend": key,
        "session_id": _safe_session_id(session_id),
        "code_sha256": hashlib.sha256(str(code).encode("utf-8")).hexdigest(),
        "state_path": state_rel,
        "history_path": history_rel,
        "image": image,
        "timeout_seconds": max(1, min(int(timeout_seconds), 600)),
        "memory_mb": max(64, min(int(memory_mb), 8192)),
        "network_enabled": bool(network_enabled),
        "command": ["python", "-I", "-c", wrapper],
    }
    plan = {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        **payload,
        "approval_fingerprint": _digest(payload),
        "stateful_json_namespace": True,
        "non_json_objects_persisted": False,
    }
    if key == "container":
        sandbox = sandbox_runner.sandbox_shell_plan(
            workspace,
            payload["command"],
            image=image,
            network_enabled=network_enabled,
            workspace_write=True,
            timeout_seconds=payload["timeout_seconds"],
            memory_mb=payload["memory_mb"],
        )
        plan["execution_class"] = "CONTAINER_SANDBOX"
        plan["sandbox_plan"] = sandbox
    else:
        plan["execution_class"] = "LOCAL_CONSTRAINED"
        plan["sandboxed"] = False
    return plan


def _parse_repl_output(stdout: str) -> dict[str, Any]:
    lines = [line for line in str(stdout).splitlines() if line.strip()]
    if not lines:
        return {"status": "FAIL", "reason": "REPL produced no result envelope"}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"status": "FAIL", "reason": "REPL result envelope was not valid JSON", "raw": stdout}


def python_repl_run(
    workspace: str | Path,
    code: str,
    *,
    approval_fingerprint: str,
    session_id: str = "default",
    backend: str = "container",
    image: str = "python:3.12-slim",
    timeout_seconds: int = 60,
    memory_mb: int = 512,
    network_enabled: bool = False,
) -> dict[str, Any]:
    plan = python_repl_plan(
        workspace,
        code,
        session_id=session_id,
        backend=backend,
        image=image,
        timeout_seconds=timeout_seconds,
        memory_mb=memory_mb,
        network_enabled=network_enabled,
    )
    if approval_fingerprint != plan["approval_fingerprint"]:
        return {**plan, "status": "STALE_APPROVAL"}
    if plan["backend"] == "container":
        sandbox_plan = plan["sandbox_plan"]
        result = sandbox_runner.sandbox_shell_run(
            workspace,
            plan["command"],
            approval_fingerprint=sandbox_plan["approval_fingerprint"],
            image=image,
            network_enabled=network_enabled,
            workspace_write=True,
            timeout_seconds=plan["timeout_seconds"],
            memory_mb=plan["memory_mb"],
        )
        if result["status"] != "PASS":
            return {
                "status": result["status"],
                "execution_class": "CONTAINER_SANDBOX",
                "sandbox": result,
                "approval_fingerprint": plan["approval_fingerprint"],
            }
        envelope = _parse_repl_output(result["stdout"])
        return {
            **envelope,
            "execution_class": "CONTAINER_SANDBOX",
            "sandboxed": True,
            "session_id": plan["session_id"],
            "state_path": plan["state_path"],
            "history_path": plan["history_path"],
            "approval_fingerprint": plan["approval_fingerprint"],
        }

    result = run_command(
        workspace,
        plan["command"],
        timeout_seconds=plan["timeout_seconds"],
    )
    if result["status"] != "PASS":
        return {
            "status": result["status"],
            "execution_class": "LOCAL_CONSTRAINED",
            "sandboxed": False,
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "approval_fingerprint": plan["approval_fingerprint"],
        }
    envelope = _parse_repl_output(result["stdout"])
    return {
        **envelope,
        "execution_class": "LOCAL_CONSTRAINED",
        "sandboxed": False,
        "session_id": plan["session_id"],
        "state_path": plan["state_path"],
        "history_path": plan["history_path"],
        "approval_fingerprint": plan["approval_fingerprint"],
    }


def python_repl_state(workspace: str | Path, session_id: str = "default") -> dict[str, Any]:
    state_path, history_path = _repl_paths(workspace, session_id)
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    history: list[dict[str, Any]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                history.append(json.loads(line))
    return {
        "status": "PASS",
        "session_id": _safe_session_id(session_id),
        "state": state,
        "history": history,
        "state_fingerprint": _digest(state),
        "history_fingerprint": _digest(history),
    }


def python_repl_reset(workspace: str | Path, session_id: str = "default") -> dict[str, Any]:
    state_path, history_path = _repl_paths(workspace, session_id)
    removed = []
    for path in (state_path, history_path):
        if path.exists():
            path.unlink()
            removed.append(path.name)
    return {
        "status": "PASS",
        "session_id": _safe_session_id(session_id),
        "removed": removed,
    }
