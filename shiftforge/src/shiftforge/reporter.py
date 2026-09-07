from __future__ import annotations

import json
from pathlib import Path
from .models import ProjectReport


def markdown_report(report: ProjectReport) -> str:
    lines = [
        "# ShiftForge Conversion Report",
        "",
        f"- Project: `{report.project_root}`",
        f"- Models discovered: **{report.models_discovered}**",
        f"- Models converted: **{report.models_converted}**",
        f"- Models with warnings: **{report.models_with_warnings}**",
        f"- Models with errors: **{report.models_with_errors}**",
        "",
    ]
    for r in report.results:
        lines += [f"## {r.model}", "", f"Status: **{r.status}**", ""]
        if r.required_sort_keys:
            lines.append("Sort keys: " + ", ".join(f"`{k}`" for k in r.required_sort_keys))
            lines.append("")
        for hit in r.hits:
            lines.append(f"- **{hit.rule_id}** [{hit.severity.value}] {hit.message}")
        if not r.hits:
            lines.append("- No compatibility rules triggered.")
        lines.append("")
    return "\n".join(lines)


def write_report(report: ProjectReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "conversion-report.json"
    md_path = output_dir / "conversion-report.md"
    json_path.write_text(json.dumps(report.model_dump(), indent=2))
    md_path.write_text(markdown_report(report))
    return json_path, md_path
