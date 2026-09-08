from pathlib import Path

import pytest

from agentic_data_platform.interface import AgenticService
from agentic_data_platform.models import ActorMode
from agentic_data_platform.tui.commands import COMMANDS, execute


def test_required_slash_commands_are_registered():
    required = {
        "discover", "project", "connect", "providers", "models", "skills",
        "sql-review", "sql-translate", "query-optimize", "data-parity",
        "pii-audit", "cost-report", "lineage-diff", "dbt-develop", "dbt-test",
        "dbt-unit-tests", "dbt-docs", "dbt-analyze", "dbt-troubleshoot",
        "dbt-pr-review", "dbt-schema-verify", "airflow-analyze",
        "airflow-troubleshoot", "root-cause", "pipeline-health", "train",
        "teach", "training-status", "trace", "sessions",
    }
    assert required <= set(COMMANDS)


def test_mode_switching_preserves_policy_modes(tmp_path: Path):
    service = AgenticService(tmp_path)
    assert execute("/mode plan", service)["mode"] == "PLAN"
    assert execute("/mode builder", service)["mode"] == "BUILDER"
    assert execute("/mode admin", service)["mode"] == "ADMIN"
    assert service.actor_mode is ActorMode.ADMIN


def test_unknown_command_fails_closed(tmp_path: Path):
    service = AgenticService(tmp_path)
    with pytest.raises(KeyError):
        execute("/definitely-not-real", service)
