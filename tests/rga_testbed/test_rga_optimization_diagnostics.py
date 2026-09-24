from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _module():
    return load_module(
        "rga_optimization_diagnostics_test",
        ROOT / "scripts" / "rga_testbed" / "execute_optimization_diagnostics.py",
    )


def test_diagnostic_executor_accepts_only_allowlisted_selects(tmp_path: Path):
    module = _module()
    sql_file = tmp_path / "diagnostics.sql"
    sql_file.write_text(
        """
        -- comment
        SELECT SYSTEM$ESTIMATE_QUERY_ACCELERATION('qid-1');
        SELECT SYSTEM$CLUSTERING_INFORMATION('DB.S.T', '(C1)');
        SELECT SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS(
          'DB.S.T', 'EQUALITY(C1)'
        );
        -- ALTER TABLE DB.S.T CLUSTER BY (C1);
        """,
        encoding="utf-8",
    )
    errors, statements = module.validate_request(
        sql_file,
        confirm=False,
        dry_run=True,
    )
    assert errors == []
    assert len(statements) == 3
    assert all(statement.upper().startswith("SELECT") for statement in statements)


def test_diagnostic_executor_refuses_mutation_even_with_confirm(tmp_path: Path):
    module = _module()
    sql_file = tmp_path / "unsafe.sql"
    sql_file.write_text(
        "ALTER TABLE DB.S.T CLUSTER BY (C1);\n",
        encoding="utf-8",
    )
    errors, statements = module.validate_request(
        sql_file,
        confirm=True,
        dry_run=False,
    )
    assert statements == ["ALTER TABLE DB.S.T CLUSTER BY (C1)"]
    assert any("not SELECT-only" in error for error in errors)


def test_diagnostic_executor_refuses_unapproved_select(tmp_path: Path):
    module = _module()
    sql_file = tmp_path / "unsafe-select.sql"
    sql_file.write_text("SELECT * FROM DB.S.T;\n", encoding="utf-8")
    errors, _ = module.validate_request(
        sql_file,
        confirm=True,
        dry_run=False,
    )
    assert any("approved optimization diagnostic" in error for error in errors)


def test_diagnostic_executor_live_mode_requires_confirmation(tmp_path: Path):
    module = _module()
    sql_file = tmp_path / "diagnostics.sql"
    sql_file.write_text(
        "SELECT SYSTEM$ESTIMATE_QUERY_ACCELERATION('qid-1');\n",
        encoding="utf-8",
    )
    errors, statements = module.validate_request(
        sql_file,
        confirm=False,
        dry_run=False,
    )
    assert len(statements) == 1
    assert "Refusing live optimization diagnostics without --confirm" in errors
