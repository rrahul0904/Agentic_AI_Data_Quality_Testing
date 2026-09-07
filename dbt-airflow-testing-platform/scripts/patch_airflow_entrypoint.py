"""Idempotently patches .airflow_venv/bin/airflow with a macOS fork-safety
workaround. Run by setup_airflow_venv.sh; safe to re-run.

Why this exists, and why it patches the *entrypoint script* rather than
using a sitecustomize.py: see docs/RUNBOOK.md ("Individual tasks hang at
90%+ CPU forever"). Short version -- Airflow's StandardTaskRunner forks by
default, which SIGSEGVs/deadlocks in some sandboxed/macOS setups. Every
Airflow process (scheduler, triggerer, and the `airflow tasks run --local`/
`--raw` subprocesses SequentialExecutor spawns for each task) goes through
this same `bin/airflow` script, so patching it here -- rather than relying
on sitecustomize.py, which a system Python install can silently shadow, as
happened here with Homebrew's own sitecustomize.py -- reliably reaches every
one of them.

The patch only takes effect when ADE_FORCE_EXEC_TASK_RUNNER is set in the
environment, so it's inert (a 2-line no-op check) anywhere that isn't set,
e.g. a normal Linux deployment.
"""

import sys
from pathlib import Path

MARKER = "# --- ADE macOS fork-safety patch ---"

PATCH = f'''{MARKER}
import os as _ade_os
if _ade_os.environ.get("ADE_FORCE_EXEC_TASK_RUNNER"):
    from airflow import settings as _ade_settings
    _ade_settings.CAN_FORK = False
{MARKER}
'''


def main() -> None:
    venv_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".airflow_venv")
    entrypoint = venv_dir / "bin" / "airflow"
    content = entrypoint.read_text()

    if MARKER in content:
        print(f"{entrypoint}: already patched, skipping")
        return

    needle = "import sys\nfrom airflow.__main__ import main\n"
    if needle not in content:
        raise SystemExit(f"{entrypoint}: expected content not found; airflow's console-script format may have changed")

    content = content.replace(needle, needle + PATCH)
    entrypoint.write_text(content)
    print(f"{entrypoint}: patched")


if __name__ == "__main__":
    main()
