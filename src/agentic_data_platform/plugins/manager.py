from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HookResult:
    plugin: str
    hook: str
    success: bool
    result: Any = None
    error: str | None = None


class PluginManager:
    """Synchronous, failure-isolated plugin hook dispatcher."""

    SUPPORTED_HOOKS = frozenset({
        "session.start", "session.end", "generation.start", "generation.end",
        "tool.before", "tool.after", "permission.before",
        "file.before_write", "file.after_write",
    })

    def __init__(self) -> None:
        self._hooks: dict[str, list[tuple[str, Callable[[dict[str, Any]], Any]]]] = defaultdict(list)

    def register(self, plugin: str, hook: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        if hook not in self.SUPPORTED_HOOKS:
            raise ValueError(f"unsupported plugin hook: {hook}")
        self._hooks[hook].append((plugin, handler))

    def emit(self, hook: str, payload: dict[str, Any]) -> list[HookResult]:
        if hook not in self.SUPPORTED_HOOKS:
            raise ValueError(f"unsupported plugin hook: {hook}")
        results: list[HookResult] = []
        for plugin, handler in tuple(self._hooks.get(hook, ())):
            try:
                results.append(HookResult(plugin, hook, True, handler(dict(payload))))
            except Exception as exc:
                results.append(HookResult(plugin, hook, False, error=f"{type(exc).__name__}: {exc}"))
        return results
