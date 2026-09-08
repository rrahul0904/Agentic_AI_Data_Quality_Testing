from pathlib import Path

from agentic_data_platform.airflow_compat import AirflowControlPlane
from agentic_data_platform.tools.builtin import build_tool_registry


def test_fresh_checkout_import_and_core_artifacts():
    root = Path(__file__).resolve().parents[2]
    assert (root / "pyproject.toml").is_file()
    assert (root / "apps" / "web" / "package.json").is_file()
    assert (root / "hospitality-snowflake-data-platform").is_dir()
    assert len(build_tool_registry().definitions()) >= 285
    assert AirflowControlPlane(root / "hospitality-snowflake-data-platform").inventory()["dag_count"] >= 40
