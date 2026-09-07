# Publication baseline — 2026-09-07

The control-plane registry contains 44 tools before this implementation wave.
Verified locally: root 94 tests; hospitality 7 tests and Ruff; LDH 10 tests
and 4/4 static quality checks; ShiftForge 6 tests; integration 7 tests;
root Ruff; static Airflow 55 DAGs, zero parse errors. dbt parse succeeded
using dbt-core 1.12.3 through its Python entry point and an ephemeral profile
with placeholder credentials. No live warehouse queries were used.

The system dbt launcher and the relocated hospitality venv launcher do not
work from this checkout; the installed dbt Python API works. Fresh-install CI
reproducibility will be addressed in the implementation wave.

The older dbt-airflow-testing-platform backend is included as a source snapshot
at local commit 7cfcbdf, plus its two handoff documents. Its nested Git history
is preserved locally. The parent ignore rule protects its 2.5 GB runtime tree;
explicitly tracked source files remain in the consolidated repository.

All eight files above 90 MiB are ignored dependencies/runtime executables.
No generated datasets, credentials, runtime databases, or virtual environments
are included. Secret-pattern findings were environment variable references
and template placeholders. Docker and live Snowflake/Oracle checks: SKIP.
