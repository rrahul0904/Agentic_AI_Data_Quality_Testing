from __future__ import annotations

import json
from pathlib import Path
import typer
from .engine import ConversionEngine
from .reporter import write_report
from .validator import compile_isolated

app = typer.Typer(help="Local-first dbt warehouse migration agent.", no_args_is_help=True)


@app.command()
def scan(project: Path = typer.Argument(..., exists=True, file_okay=False)):
    from .dbt import discover_models
    models = discover_models(project)
    typer.echo(f"Discovered {len(models)} dbt model(s)")
    for p in models:
        typer.echo(f" - {p.relative_to(project)}")


@app.command()
def convert(
    project: Path = typer.Argument(..., exists=True, file_okay=False),
    output: Path | None = typer.Option(None, "--output", "-o"),
    hints_file: Path | None = typer.Option(None, "--hints", help="JSON mapping model paths to sort-key source expressions."),
    approve: bool = typer.Option(False, "--approve", help="Actually write converted files. Dry-run is the default."),
    validate: bool = typer.Option(False, "--validate", help="Run dbt compile in an isolated temp project."),
):
    hints = json.loads(hints_file.read_text()) if hints_file else {}
    engine = ConversionEngine()
    report = engine.convert_project(project, output_dir=output, hints=hints, write=approve)
    out = Path(report.metadata["output_dir"])
    if approve:
        json_path, md_path = write_report(report, out)
        typer.echo(f"Wrote {report.models_converted} model(s) to {out}")
        typer.echo(f"Reports: {json_path.name}, {md_path.name}")
    else:
        typer.echo("DRY RUN — no files were written. Pass --approve to write output.")
    typer.echo(f"warnings={report.models_with_warnings} errors={report.models_with_errors}")
    for r in report.results:
        typer.echo(f"[{r.status}] {r.model}  rules={len(r.hits)} unresolved={','.join(r.unresolved) or '-'}")
    if validate:
        if not approve:
            raise typer.BadParameter("--validate requires --approve so there is an isolated converted tree to overlay")
        result = compile_isolated(project, out)
        typer.echo(f"dbt compile exit={result.exit_code}")
        if result.stdout:
            typer.echo(result.stdout)
        if result.stderr:
            typer.echo(result.stderr)
        raise typer.Exit(code=0 if result.ok else 2)


@app.command("convert-sql")
def convert_sql(
    file: Path = typer.Argument(..., exists=True, dir_okay=False),
    hint: list[str] = typer.Option([], "--hint", help="key=source_expression, repeatable"),
):
    hints: dict[str, str] = {}
    for item in hint:
        key, sep, value = item.partition("=")
        if not sep:
            raise typer.BadParameter("Hint must be key=expression")
        hints[key] = value
    result = ConversionEngine().convert_sql(file.read_text(), file.name, hints)
    typer.echo(result.converted_sql)
    typer.echo("\n--- findings ---")
    for h in result.hits:
        typer.echo(f"{h.rule_id} [{h.severity.value}] {h.message}")
