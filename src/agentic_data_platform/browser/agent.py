"""Governed agent-browser adapter for ADE."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import urlparse


_READ_ACTIONS = frozenset({"open", "snapshot", "get-text", "get-url", "get-title", "wait", "screenshot"})
_INTERACTIVE_ACTIONS = frozenset({"click", "fill", "type", "select", "check", "press", "scroll"})
_ALL_ACTIONS = _READ_ACTIONS | _INTERACTIVE_ACTIONS


@dataclass(frozen=True)
class BrowserPlan:
    session: str
    actions: tuple[dict[str, Any], ...]
    interactive: bool

    def public(self) -> dict[str, Any]:
        return {
            "status": "PASS",
            "session": self.session,
            "interactive": self.interactive,
            "action_count": len(self.actions),
            "actions": list(self.actions),
        }


def _safe_url(value: str) -> str:
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("browser URL must use http or https")
    if not parsed.netloc:
        raise ValueError("browser URL requires a host")
    return str(value)


def _ref(value: str) -> str:
    text = str(value)
    if not text.startswith("@e") or not text[2:].isdigit():
        raise ValueError("browser element reference must look like @e1")
    return text


def plan_browser_actions(actions: list[dict[str, Any]], *, session: str = "ade") -> BrowserPlan:
    normalized = []
    interactive = False
    for item in actions:
        action = str(item.get("action") or "").casefold()
        if action not in _ALL_ACTIONS:
            raise ValueError(f"unsupported browser action: {action}")
        value = dict(item)
        value["action"] = action
        if action == "open":
            value["url"] = _safe_url(str(value["url"]))
        if action in {"click", "fill", "type", "select", "check", "get-text"}:
            value["ref"] = _ref(str(value["ref"]))
        if action in _INTERACTIVE_ACTIONS:
            interactive = True
        normalized.append(value)
    return BrowserPlan(str(session or "ade"), tuple(normalized), interactive)


def _command(session: str, action: dict[str, Any]) -> list[str]:
    base = ["agent-browser", "--session", session]
    name = action["action"]
    if name == "open":
        return [*base, "open", action["url"]]
    if name == "snapshot":
        command = [*base, "snapshot", "-i"]
        if action.get("cursor"):
            command.append("-C")
        return command
    if name == "click":
        return [*base, "click", action["ref"]]
    if name in {"fill", "type"}:
        return [*base, name, action["ref"], str(action.get("text") or "")]
    if name == "select":
        return [*base, "select", action["ref"], str(action["value"])]
    if name == "check":
        return [*base, "check", action["ref"]]
    if name == "press":
        return [*base, "press", str(action["key"])]
    if name == "scroll":
        direction = str(action.get("direction") or "down").casefold()
        if direction not in {"up", "down", "left", "right"}:
            raise ValueError("scroll direction must be up/down/left/right")
        return [*base, "scroll", direction, str(int(action.get("amount", 500)))]
    if name == "get-text":
        return [*base, "get", "text", action["ref"]]
    if name == "get-url":
        return [*base, "get", "url"]
    if name == "get-title":
        return [*base, "get", "title"]
    if name == "wait":
        if action.get("ref"):
            return [*base, "wait", _ref(str(action["ref"]))]
        if action.get("load"):
            mode = str(action["load"])
            if mode not in {"networkidle", "domcontentloaded", "load"}:
                raise ValueError("unsupported browser load wait mode")
            return [*base, "wait", "--load", mode]
        return [*base, "wait", str(int(action.get("milliseconds", 1000)))]
    if name == "screenshot":
        command = [*base, "screenshot"]
        if action.get("full"):
            command.append("--full")
        if action.get("annotate"):
            command.append("--annotate")
        if action.get("path"):
            path = Path(str(action["path"]))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("screenshot path must be project-relative")
            command.append(path.as_posix())
        return command
    raise AssertionError(name)


class AgentBrowser:
    def __init__(self, executor: Callable[[list[str]], dict[str, Any]] | None = None) -> None:
        self.executor = executor

    def execute(
        self,
        actions: list[dict[str, Any]],
        *,
        session: str = "ade",
        allow_interactive: bool = False,
    ) -> dict[str, Any]:
        plan = plan_browser_actions(actions, session=session)
        if plan.interactive and not allow_interactive:
            return {
                **plan.public(),
                "status": "BLOCKED_APPROVAL",
                "reason": "interactive browser actions require explicit approval",
            }
        if self.executor is None and shutil.which("agent-browser") is None:
            return {
                **plan.public(),
                "status": "SKIP_EXTERNAL",
                "reason": "agent-browser executable is not installed",
            }

        results = []
        for action in plan.actions:
            command = _command(plan.session, action)
            if self.executor is not None:
                result = dict(self.executor(command))
            else:
                process = subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
                result = {
                    "returncode": process.returncode,
                    "stdout": process.stdout[-12000:],
                    "stderr": process.stderr[-8000:],
                }
            result["command"] = command
            results.append(result)
            if int(result.get("returncode", 0)) != 0:
                return {
                    **plan.public(),
                    "status": "FAIL",
                    "results": results,
                }
        return {
            **plan.public(),
            "status": "PASS",
            "results": results,
        }

    @staticmethod
    def close_command(*, session: str = "ade") -> list[str]:
        return ["agent-browser", "--session", str(session), "close"]
