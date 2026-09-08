from __future__ import annotations

from agentic_data_platform.teammates import TeammateManager
from agentic_data_platform.tools.builtin import build_tool_registry


def test_local_teammate_manager_full_lifecycle(tmp_path):
    manager = TeammateManager(
        tmp_path,
        database=tmp_path / ".ade" / "teammates.db",
        global_root=tmp_path / "global",
    )

    integrations = manager.execute("list-integrations", {})
    assert integrations["count"] >= 2
    assert {"filesystem", "github"}.issubset(
        {item["id"] for item in integrations["integrations"]}
    )

    created = manager.execute(
        "create",
        {
            "name": "Data Reviewer",
            "description": "Reviews data quality",
            "integration_ids": ["filesystem"],
            "memory_enabled": True,
            "privacy": "private",
        },
    )
    teammate = created["teammate"]
    teammate_id = teammate["teammate_id"]
    assert teammate["name"] == "Data Reviewer"

    listed = manager.execute("list", {})
    assert listed["count"] == 1

    edited = manager.execute(
        "edit",
        {
            "datamate_id": teammate_id,
            "name": "Data Quality Reviewer",
            "integration_ids": ["filesystem", "github"],
            "privacy": "public",
        },
    )
    assert edited["teammate"]["privacy"] == "public"
    assert edited["teammate"]["integration_ids"] == ["filesystem", "github"]

    added = manager.execute(
        "add",
        {
            "datamate_id": teammate_id,
            "scope": "project",
        },
    )
    assert added["status"] == "PASS"
    assert len(added["servers"]) == 2
    assert all(name.startswith("teammate-data-quality-reviewer-") for name in added["servers"])

    status = manager.execute("status", {})
    assert status["count"] == 2
    configs = manager.execute("list-config", {})
    assert configs["count"] == 2
    assert all(item["scope"] == "project" for item in configs["entries"])

    removed = manager.execute(
        "remove",
        {
            "datamate_id": teammate_id,
            "scope": "project",
        },
    )
    assert removed["count"] == 2
    assert manager.execute("status", {})["count"] == 0

    deleted = manager.execute(
        "delete",
        {"datamate_id": teammate_id},
    )
    assert deleted["deleted"] is True
    assert manager.execute("list", {})["count"] == 0


def test_teammate_manager_rejects_unknown_integrations(tmp_path):
    manager = TeammateManager(tmp_path, global_root=tmp_path / "global")
    try:
        manager.execute(
            "create",
            {
                "name": "Bad",
                "integration_ids": ["not-real"],
            },
        )
    except KeyError as exc:
        assert "not-real" in str(exc)
    else:
        raise AssertionError("unknown integration must be rejected")


def test_registry_exposes_datamate_compatibility_tool():
    definition = build_tool_registry().describe("datamate_manager")
    assert definition.name == "datamate_manager"
    assert definition.risk.value == "mutating"
