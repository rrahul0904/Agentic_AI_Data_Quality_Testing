from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class HookResult:
    plugin: str
    hook: str
    success: bool
    result: Any = None
    error: str | None = None


@dataclass(frozen=True)
class HookDecision:
    hook: str
    blocked: bool
    reason: str | None
    payload: dict[str, Any]
    modified: bool
    results: tuple[HookResult, ...]

    def public(self) -> dict[str, Any]:
        return {
            "hook": self.hook,
            "blocked": self.blocked,
            "reason": self.reason,
            "payload": self.payload,
            "modified": self.modified,
            "results": [asdict(item) for item in self.results],
        }


class PluginManager:
    """Synchronous plugin hook dispatcher with enforceable before-hook decisions.

    Ordinary hooks remain failure-isolated observations. Policy-sensitive before
    hooks may return:
      {"action": "allow"}
      {"action": "block", "reason": "..."}
      {"action": "modify", "updates": {...}}

    A plugin exception never silently blocks work; it is recorded as failed hook
    evidence. Explicit blocking must be returned intentionally.
    """

    SUPPORTED_HOOKS = frozenset({
        "session.start", "session.end",
        "generation.start", "generation.end", "generation.before", "generation.after",
        "tool.before", "tool.after", "permission.before",
        "file.before_write", "file.after_write",
    })
    ENFORCEABLE_HOOKS = frozenset({
        "generation.before",
        "tool.before",
        "permission.before",
        "file.before_write",
    })

    def __init__(self) -> None:
        self._hooks: dict[str, list[tuple[str, Callable[[dict[str, Any]], Any]]]] = defaultdict(list)

    def register(self, plugin: str, hook: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        if hook not in self.SUPPORTED_HOOKS:
            raise ValueError(f"unsupported plugin hook: {hook}")
        self._hooks[hook].append((plugin, handler))

    def unregister_plugin(self, plugin: str) -> int:
        removed = 0
        for hook in tuple(self._hooks):
            before = len(self._hooks[hook])
            self._hooks[hook] = [item for item in self._hooks[hook] if item[0] != plugin]
            removed += before - len(self._hooks[hook])
        return removed

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

    def evaluate(self, hook: str, payload: dict[str, Any]) -> HookDecision:
        if hook not in self.ENFORCEABLE_HOOKS:
            raise ValueError(f"hook is not enforceable: {hook}")

        current = dict(payload)
        modified = False
        blocked = False
        reason: str | None = None
        results: list[HookResult] = []

        for plugin, handler in tuple(self._hooks.get(hook, ())):
            try:
                raw = handler(dict(current))
                result = HookResult(plugin, hook, True, raw)
                results.append(result)
            except Exception as exc:
                results.append(HookResult(plugin, hook, False, error=f"{type(exc).__name__}: {exc}"))
                continue

            if not isinstance(raw, dict):
                continue
            action = str(raw.get("action") or "allow").casefold()

            if action == "block":
                blocked = True
                reason = str(raw.get("reason") or f"blocked by plugin {plugin}")
                break

            if action == "modify":
                updates = raw.get("updates")
                if not isinstance(updates, dict):
                    raise ValueError(f"plugin {plugin} returned modify without object updates")
                current.update(updates)
                modified = True
                continue

            if action not in {"allow", "observe", "noop"}:
                raise ValueError(f"unsupported hook action from {plugin}: {action}")

        return HookDecision(
            hook=hook,
            blocked=blocked,
            reason=reason,
            payload=current,
            modified=modified,
            results=tuple(results),
        )
