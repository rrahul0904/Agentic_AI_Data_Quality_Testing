#!/usr/bin/env python3
"""Render guarded Snowflake physical-optimization experiments from workload analysis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _emit_experiment(lines: list[str], item: dict[str, Any], index: int) -> None:
    kind = item.get("type", "unknown")
    lines.append(f"-- Experiment {index}: {kind}")
    if item.get("confidence"):
        lines.append(f"-- confidence={item['confidence']}")
    if item.get("reason"):
        lines.append(f"-- reason: {item['reason']}")
    if item.get("fingerprint"):
        lines.append(f"-- fingerprint={item['fingerprint']}")
    if item.get("representative_query_id"):
        lines.append(f"-- representative_query_id={item['representative_query_id']}")
    if item.get("table"):
        lines.append(f"-- table={item['table']}")
    if item.get("columns"):
        lines.append("-- columns=" + ", ".join(item["columns"]))

    read_only = item.get("estimate_sql") or item.get("diagnostic_sql")
    if read_only:
        lines.append("-- READ-ONLY EVIDENCE QUERY")
        lines.append(str(read_only).rstrip())

    mutation = item.get("mutation_sql")
    if mutation:
        lines.append("-- CANDIDATE MUTATION — intentionally commented out")
        guard = item.get("mutation_guard")
        if guard:
            lines.append(f"-- guard: {guard}")
        for mutation_line in str(mutation).rstrip().splitlines():
            lines.append("-- " + mutation_line)

    if kind == "warehouse_concurrency":
        lines.append(
            "-- CANDIDATE CONFIGURATION: compare multi-cluster/concurrency settings under the same benchmark sweep."
        )
    elif kind == "warehouse_size_or_query_shape":
        lines.append(
            "-- CANDIDATE CONFIGURATION: compare one warehouse-size step and/or reduce intermediate query shape."
        )
    elif kind == "semantic_view_materialization":
        lines.append(
            "-- CANDIDATE CONFIGURATION: use the separately generated governed Semantic View materialization pack."
        )
    elif kind == "aggregate_or_dynamic_table":
        lines.append(
            "-- CANDIDATE CONFIGURATION: build a temporary aggregate/Dynamic Table experiment at the verified grain."
        )
    lines.append("")


def render(analysis: dict[str, Any]) -> str:
    lines = [
        "-- Governed semantic platform physical-optimization experiments.",
        "-- Read-only diagnostics/estimates may be executed after normal Snowflake authorization.",
        "-- Physical mutations are NEVER emitted as executable statements by this file.",
        "-- Semantic metric definitions must remain unchanged.",
        "",
    ]

    index = 1
    for recommendation in analysis.get("recommendations", []):
        for experiment in recommendation.get("experiments", []):
            item = {
                **experiment,
                "fingerprint": recommendation.get("fingerprint"),
                "confidence": recommendation.get("confidence"),
                "reason": "; ".join(recommendation.get("reasons", [])),
            }
            _emit_experiment(lines, item, index)
            index += 1

    for experiment in analysis.get("query_history", {}).get("experiments", []):
        _emit_experiment(lines, experiment, index)
        index += 1

    if index == 1:
        lines.append("-- No acceleration experiments were justified by the supplied evidence.")
        lines.append("")

    return "\n".join(lines)


def generate(analysis_path: Path, output: Path) -> dict[str, Any]:
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    text = render(analysis)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    executable_mutation_lines = [
        line
        for line in text.splitlines()
        if line.strip().upper().startswith(("ALTER TABLE", "ALTER WAREHOUSE", "CREATE DYNAMIC TABLE"))
    ]
    if executable_mutation_lines:
        raise RuntimeError(
            "Optimization experiment pack accidentally emitted executable physical mutations"
        )
    return {
        "status": "PASS",
        "output": str(output),
        "experiment_count": sum(
            len(item.get("experiments", []))
            for item in analysis.get("recommendations", [])
        )
        + len(analysis.get("query_history", {}).get("experiments", [])),
        "executable_physical_mutations": 0,
    }


def main() -> int:
    args = parse_args()
    try:
        report = generate(args.analysis, args.output)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
