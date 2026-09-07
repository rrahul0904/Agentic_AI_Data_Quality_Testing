from __future__ import annotations
from typing import Any, Sequence

def estimate_tokens(value: str) -> int:
    return max(1, (len(value) + 3) // 4)

class ContextManager:
    def __init__(self, max_tokens: int = 120_000, reserve_tokens: int = 8_000) -> None:
        if max_tokens <= reserve_tokens:
            raise ValueError("max_tokens must exceed reserve_tokens")
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens
    def count_messages(self, messages: Sequence[dict[str, Any]]) -> int:
        return sum(estimate_tokens(str(message.get("content", ""))) + 8 for message in messages)
    def compact(self, messages: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        items = [dict(message) for message in messages]
        budget = self.max_tokens - self.reserve_tokens
        original = self.count_messages(items)
        if original <= budget:
            return items, {"compacted": False, "before_tokens": original, "after_tokens": original}
        system = [item for item in items if item.get("role") == "system"][:1]
        non_system = [item for item in items if item.get("role") != "system"]
        kept, used = [], self.count_messages(system)
        for item in reversed(non_system):
            cost = self.count_messages([item])
            if kept and used + cost > budget:
                break
            kept.append(item)
            used += cost
        kept.reverse()
        removed = max(0, len(non_system) - len(kept))
        marker = {"role": "system", "content": f"[Context compacted: {removed} earlier messages omitted; retrieve session trace if needed.]"}
        result = [*system, marker, *kept]
        return result, {"compacted": True, "removed_messages": removed, "before_tokens": original, "after_tokens": self.count_messages(result)}
