from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ValidationResult:
    ok: bool
    command: list[str]
    stdout: str
    stderr: str
    exit_code: int


def dbt_available() -> bool:
    return shutil.which("dbt") is not None


def compile_isolated(project_root: Path, converted_root: Path, select: list[str] | None = None) -> ValidationResult:
    """Validate converted models without mutating the source repository.

    Copies the dbt project to a temporary workspace and overlays converted models there,
    so duplicate model names under a `models/converted` folder never pollute the source project.
    """
    if not dbt_available():
        return ValidationResult(False, ["dbt", "compile"], "", "dbt executable not found", 127)
    with tempfile.TemporaryDirectory(prefix="shiftforge-") as tmp:
        tmp_root = Path(tmp) / project_root.name
        shutil.copytree(project_root, tmp_root)
        for converted in converted_root.rglob("*.sql"):
            try:
                rel = converted.relative_to(converted_root)
            except ValueError:
                continue
            dest = tmp_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(converted, dest)
        cmd = ["dbt", "compile", "--project-dir", str(tmp_root)]
        if select:
            cmd += ["--select", *select]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_root)
        return ValidationResult(proc.returncode == 0, cmd, proc.stdout, proc.stderr, proc.returncode)
