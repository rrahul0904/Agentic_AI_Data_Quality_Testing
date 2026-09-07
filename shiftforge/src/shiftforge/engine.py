from __future__ import annotations

from pathlib import Path
from .dbt import discover_models, enforce_sort_keys, extract_sort_keys, selected_columns
from .models import ModelResult, ProjectReport, Severity
from .rules import apply_rules


class ConversionEngine:
    def convert_sql(self, sql: str, model_name: str = "model.sql", hints: dict[str, str] | None = None) -> ModelResult:
        converted, hits = apply_rules(sql)
        converted, sort_hits, unresolved = enforce_sort_keys(converted, hints=hints)
        hits.extend(sort_hits)
        status = "needs_review" if unresolved or any(h.severity == Severity.warning for h in hits) else "converted"
        if any(h.severity == Severity.error for h in hits):
            status = "blocked"
        return ModelResult(
            model=model_name,
            source_path=model_name,
            converted_sql=converted,
            hits=hits,
            selected_columns=selected_columns(converted),
            required_sort_keys=extract_sort_keys(converted),
            unresolved=unresolved,
            status=status,
        )

    def convert_project(self, project_root: Path, output_dir: Path | None = None,
                        hints: dict[str, dict[str, str]] | None = None, write: bool = False) -> ProjectReport:
        project_root = project_root.resolve()
        output_dir = (output_dir or (project_root.parent / f"{project_root.name}-redshift-converted")).resolve()
        hints = hints or {}
        models = discover_models(project_root)
        results: list[ModelResult] = []
        for model in models:
            rel = model.relative_to(project_root)
            result = self.convert_sql(model.read_text(), str(rel), hints=hints.get(str(rel), {}))
            dest = output_dir / rel
            result.output_path = str(dest)
            if write:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(result.converted_sql)
            results.append(result)
        warnings = sum(1 for r in results if any(h.severity == Severity.warning for h in r.hits))
        errors = sum(1 for r in results if any(h.severity == Severity.error for h in r.hits))
        return ProjectReport(
            project_root=str(project_root),
            models_discovered=len(models),
            models_converted=len(results),
            models_with_warnings=warnings,
            models_with_errors=errors,
            results=results,
            metadata={"output_dir": str(output_dir), "write_enabled": write},
        )
