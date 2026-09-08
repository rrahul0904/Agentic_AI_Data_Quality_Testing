from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from agentic_data_platform.agents import InvestigationStore, SupervisorAgent, scenario_catalog
from agentic_data_platform.tools.builtin import build_tool_registry


def main() -> None:
    started = time.perf_counter()
    correct_root = 0
    correct_divergence = 0
    scenarios = scenario_catalog()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(__file__).resolve().parents[2]
        service = SupervisorAgent(
            build_tool_registry(),
            InvestigationStore(Path(tmp) / "agentic-benchmark.db"),
            root / "hospitality-snowflake-data-platform",
        )
        tool_calls = 0
        agent_turns = 0
        for item in scenarios:
            report = service.investigate(item["scenario_id"])
            correct_root += int(report.root_cause == item["expected_root_cause"])
            correct_divergence += int(report.first_divergence == item["expected_first_divergence"])
            tool_calls += sum(len(result.tools_used) for result in report.agent_results)
            agent_turns += len(report.agent_results)
    count = len(scenarios)
    result = {
        "scenario_count": count,
        "root_cause_accuracy": correct_root / count,
        "first_divergence_accuracy": correct_divergence / count,
        "tool_call_count": tool_calls,
        "agent_turns": agent_turns,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "llm_tokens": 0,
        "estimated_ai_cost_usd": 0.0,
        "mode": "DETERMINISTIC_LOCAL_BENCHMARK",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["root_cause_accuracy"] != 1.0 or result["first_divergence_accuracy"] != 1.0:
        raise SystemExit("agentic benchmark correctness gate failed")


if __name__ == "__main__":
    main()
