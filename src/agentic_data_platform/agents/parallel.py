"""Parallel, isolated subagent execution for ADE."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Callable, Iterable

import yaml

from agentic_data_platform.models import ActorMode, Environment
from agentic_data_platform.providers.base import Provider
from agentic_data_platform.runtime.agent import AgentRuntime
from agentic_data_platform.tools.registry import ToolRegistry


@dataclass(frozen=True)
class SubagentDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...] = ()
    model: str = "inherit"
    system_prompt: str = ""
    actor_mode: ActorMode = ActorMode.ANALYST
    max_steps: int = 8
    timeout_seconds: int = 120
    verification_contract: tuple[Any, ...] = ()
    source: str = "runtime"

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "allowed_tools": list(self.allowed_tools),
            "model": self.model,
            "system_prompt": self.system_prompt,
            "actor_mode": self.actor_mode.value,
            "max_steps": self.max_steps,
            "timeout_seconds": self.timeout_seconds,
            "verification_contract": list(self.verification_contract),
            "source": self.source,
        }


@dataclass(frozen=True)
class SubagentTask:
    definition: SubagentDefinition
    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubagentOutcome:
    name: str
    status: str
    summary: str
    duration_ms: float
    session_id: str | None = None
    trace_id: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "duration_ms": self.duration_ms,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "result": self.result,
            "verification": self.verification,
            "error": self.error,
        }


SubagentExecutor = Callable[[SubagentTask], dict[str, Any]]
ProviderFactory = Callable[[SubagentDefinition], Provider]


def _frontmatter(path: Path) -> SubagentDefinition:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"agent definition requires YAML frontmatter: {path}")
    _, raw, body = text.split("---", 2)
    metadata = yaml.safe_load(raw) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"agent frontmatter must be an object: {path}")
    name = str(metadata.get("name") or path.stem).strip()
    description = str(metadata.get("description") or "").strip()
    if not name or not description:
        raise ValueError(f"agent requires name and description: {path}")
    tools = metadata.get("tools", ())
    if tools == "*":
        allowed_tools: tuple[str, ...] = ("*",)
    elif isinstance(tools, str):
        allowed_tools = tuple(item.strip() for item in tools.split(",") if item.strip())
    elif isinstance(tools, list):
        allowed_tools = tuple(str(item) for item in tools)
    else:
        allowed_tools = ()
    actor = ActorMode(str(metadata.get("actor_mode") or "analyst"))
    return SubagentDefinition(
        name=name,
        description=description,
        allowed_tools=allowed_tools,
        model=str(metadata.get("model") or "inherit"),
        system_prompt=body.strip(),
        actor_mode=actor,
        max_steps=max(1, min(int(metadata.get("max_steps", 8)), 50)),
        timeout_seconds=max(1, min(int(metadata.get("timeout_seconds", 120)), 3600)),
        verification_contract=tuple(metadata.get("verification") or ()),
        source=str(path),
    )


class SubagentRegistry:
    """Discover project/user subagents from version-controlled Markdown definitions."""

    def __init__(self, definitions: Iterable[SubagentDefinition] = ()) -> None:
        self._definitions = {item.name: item for item in definitions}

    @classmethod
    def discover(cls, root: str | Path) -> "SubagentRegistry":
        base = Path(root).expanduser().resolve()
        definitions: list[SubagentDefinition] = []
        for folder in (base / ".ade" / "agents", base / ".agents", base / "agents"):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.md")):
                definitions.append(_frontmatter(path))
        return cls(definitions)

    def register(self, definition: SubagentDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"subagent already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> SubagentDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise KeyError(f"unknown subagent: {name}") from exc

    def list(self) -> list[dict[str, Any]]:
        return [self._definitions[name].public() for name in sorted(self._definitions)]


def verify_subagent_result(
    contract: Iterable[Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for raw in contract:
        if isinstance(raw, str):
            value = result.get(raw)
            findings.append(
                {
                    "rule": raw,
                    "actual": value,
                    "passed": bool(value),
                }
            )
            continue
        if not isinstance(raw, dict):
            findings.append(
                {
                    "rule": raw,
                    "actual": None,
                    "passed": False,
                    "reason": "verification rule must be a field name or mapping",
                }
            )
            continue
        rule = dict(raw)
        field_name = str(rule.get("field") or "")
        value = result.get(field_name) if field_name else None
        if "equals" in rule:
            passed = value == rule["equals"]
        elif "in" in rule:
            passed = value in list(rule["in"])
        elif "min" in rule:
            try:
                passed = float(value) >= float(rule["min"])
            except (TypeError, ValueError):
                passed = False
        else:
            passed = bool(value)
        findings.append(
            {
                "rule": rule,
                "actual": value,
                "passed": passed,
            }
        )
    payload = {
        "status": "PASS" if all(item["passed"] for item in findings) else "FAIL",
        "findings": findings,
    }
    import hashlib
    import json

    payload["verification_fingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return payload



class ParallelSubagentCoordinator:
    """Run independent subagents concurrently and return bounded summaries to the parent."""

    def __init__(self, executor: SubagentExecutor, *, max_workers: int = 6) -> None:
        self.executor = executor
        self.max_workers = max(1, min(int(max_workers), 32))

    def run(self, tasks: Iterable[SubagentTask]) -> dict[str, Any]:
        task_list = list(tasks)
        if not task_list:
            return {"status": "PASS", "task_count": 0, "results": []}
        outcomes: dict[int, SubagentOutcome] = {}

        def execute(index: int, task: SubagentTask) -> tuple[int, SubagentOutcome]:
            started = time.perf_counter()
            try:
                result = dict(self.executor(task))
                status = str(result.get("status") or "PASS")
                verification = verify_subagent_result(
                    task.definition.verification_contract,
                    result,
                )
                if status == "PASS" and verification["status"] != "PASS":
                    status = "FAIL_VERIFICATION"
                summary = str(
                    result.get("summary")
                    or result.get("response")
                    or result.get("claim")
                    or status
                )[:4000]
                outcome = SubagentOutcome(
                    task.definition.name,
                    status,
                    summary,
                    round((time.perf_counter() - started) * 1000, 3),
                    session_id=result.get("session_id"),
                    trace_id=result.get("trace_id"),
                    result=result,
                    verification=verification,
                )
            except Exception as exc:
                outcome = SubagentOutcome(
                    task.definition.name,
                    "FAIL",
                    "",
                    round((time.perf_counter() - started) * 1000, 3),
                    error=f"{type(exc).__name__}: {exc}",
                )
            return index, outcome

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(task_list)), thread_name_prefix="ade-subagent") as pool:
            futures = {
                pool.submit(execute, index, task): (index, task)
                for index, task in enumerate(task_list)
            }
            for future in as_completed(futures):
                index, outcome = future.result()
                outcomes[index] = outcome

        ordered = [outcomes[index].public() for index in range(len(task_list))]
        failed = [
            item
            for item in ordered
            if item["status"] in {"FAIL", "ERROR", "DENIED", "FAIL_VERIFICATION"}
        ]
        return {
            "status": "FAIL" if failed else "PASS",
            "task_count": len(task_list),
            "failed_count": len(failed),
            "results": ordered,
        }


class RuntimeSubagentExecutor:
    """Adapter that gives every delegated LLM agent an isolated ADE session and tool scope."""

    def __init__(
        self,
        runtime: AgentRuntime,
        provider_factory: ProviderFactory,
        *,
        parent_session_id: str | None = None,
        project_root: str | Path | None = None,
        environment: Environment = Environment.DEV,
        approved_tools: set[str] | None = None,
    ) -> None:
        self.runtime = runtime
        self.provider_factory = provider_factory
        self.parent_session_id = parent_session_id
        self.project_root = Path(project_root).expanduser().resolve() if project_root else None
        self.environment = environment
        self.approved_tools = approved_tools or set()

    def _scoped_registry(self, definition: SubagentDefinition) -> ToolRegistry:
        allowed = set(definition.allowed_tools)
        registry = ToolRegistry()
        for tool in self.runtime.registry.definitions():
            if "*" in allowed or tool.name in allowed:
                registry.register(tool)
        return registry

    def __call__(self, task: SubagentTask) -> dict[str, Any]:
        definition = task.definition
        parent = (
            self.runtime.store.get_session(self.parent_session_id)
            if self.parent_session_id
            else None
        )
        project_id = parent.get("project_id") if parent else None
        provider = self.provider_factory(definition)
        model = definition.model
        if model in {"inherit", "auto"}:
            model = str(parent.get("model") if parent else "") or "auto"

        session_id = self.runtime.store.create_session(
            project_id=project_id,
            title=f"Subagent: {definition.name}",
            provider=provider.name,
            model=model,
        )
        if definition.system_prompt:
            self.runtime.store.add_message(
                session_id,
                "system",
                definition.system_prompt,
                {
                    "subagent": definition.name,
                    "parent_session_id": self.parent_session_id,
                    "isolated_context": True,
                },
            )

        child_runtime = AgentRuntime(
            self._scoped_registry(definition),
            self.runtime.store,
            self.runtime.traces,
            context=self.runtime.context,
            context_sources=self.runtime.context_sources,
            plugins=self.runtime.plugins,
            max_steps=definition.max_steps,
            repeated_tool_limit=self.runtime.repeated_tool_limit,
        )
        result = child_runtime.run(
            session_id,
            task.prompt,
            provider,
            model,
            actor_mode=definition.actor_mode,
            environment=self.environment,
            approved_tools=self.approved_tools.intersection(
                set(definition.allowed_tools)
            ),
            project_root=self.project_root,
        )
        return {
            "status": "PASS",
            "summary": result.get("response") or "",
            "session_id": session_id,
            "trace_id": result.get("trace_id"),
            "response": result.get("response"),
            "steps": result.get("steps"),
            "context_sources": result.get("context_sources"),
            "parent_session_id": self.parent_session_id,
        }
