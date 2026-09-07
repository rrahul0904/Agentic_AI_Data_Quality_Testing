from __future__ import annotations

import subprocess

from agentic_data_platform.connections.driver_install import (
    install_warehouse_driver,
    warehouse_driver_status,
)


def test_driver_status_is_allowlisted():
    duck = warehouse_driver_status("duckdb")
    assert duck["status"] == "PASS"
    assert duck["package"] == "duckdb"
    unsupported = warehouse_driver_status("unknown-warehouse")
    assert unsupported["status"] == "UNSUPPORTED"


def test_driver_install_dry_run_never_executes(monkeypatch):
    monkeypatch.setattr(
        "agentic_data_platform.connections.driver_install.importlib.util.find_spec",
        lambda name: None,
    )
    result = install_warehouse_driver("oracle", dry_run=True)
    assert result["action"] == "DRY_RUN"
    assert result["command"][-1] == "oracledb"


def test_driver_install_uses_allowlisted_package_only(monkeypatch):
    monkeypatch.setattr(
        "agentic_data_platform.connections.driver_install.importlib.util.find_spec",
        lambda name: None,
    )
    calls = []

    def runner(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "installed", "")

    result = install_warehouse_driver(
        "clickhouse",
        dry_run=False,
        runner=runner,
    )
    assert result["action"] == "INSTALLED"
    assert calls[0][-1] == "clickhouse-connect"
