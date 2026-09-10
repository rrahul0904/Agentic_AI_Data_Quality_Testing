from __future__ import annotations

import json

import pytest

from agentic_data_platform.agents.parallel import SubagentRegistry
from agentic_data_platform.plugins import PluginBundleService, PluginManager
from agentic_data_platform.skills.service import SkillService


def _bundle(tmp_path):
    root = tmp_path / "bundle"
    (root / "skills" / "reservation-health").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / "commands").mkdir()
    (root / "mcp").mkdir()

    (root / "skills" / "reservation-health" / "SKILL.md").write_text(
        """---
name: reservation-health
description: Inspect reservation ingestion health.
tools:
  - semantic_search
---
Use deterministic reservation pipeline evidence.
"""
    )
    (root / "agents" / "snowflake.md").write_text(
        """---
name: snowflake-investigator
description: Investigate Snowflake failures.
tools:
  - snowflake_pipeline_rca
---
Use first-divergence evidence.
"""
    )
    (root / "commands" / "health.md").write_text("Run reservation health diagnostics.\n")
    (root / "mcp" / "catalog.json").write_text(json.dumps({
        "servers": {
            "catalog": {
                "type": "http",
                "url": "https://example.invalid/mcp",
            }
        }
    }))
    (root / "ade-plugin.yml").write_text(
        """name: reservation-ops
version: 1.2.0
description: Reservation operations bundle.
contributions:
  skills:
    - skills/reservation-health
  agents:
    - agents/snowflake.md
  commands:
    - commands/health.md
  mcp:
    - mcp/catalog.json
  hooks:
    - hook: tool.before
      action: block
      match:
        tool: snowflake_mutation_execute
        environment: prod
      reason: reservation bundle blocks production mutations
"""
    )
    return root


def test_bundle_install_activate_materializes_every_contribution(tmp_path):
    source = _bundle(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    service = PluginBundleService(project)
    plugins = PluginManager()

    validated = service.validate(source)
    assert validated["status"] == "PASS"
    assert len(validated["bundle"]["checksums"]) == 5

    installed = service.install(source)
    assert installed["name"] == "reservation-ops"
    assert installed["active"] is False

    activated = service.activate("reservation-ops", plugins=plugins)
    assert activated["status"] == "PASS"
    assert activated["registered_hooks"] == 1

    assert (project / ".ade" / "skills" / "reservation-health" / "SKILL.md").is_file()
    assert (project / ".ade" / "agents" / "snowflake.md").is_file()
    assert (project / ".ade" / "commands" / "health.md").is_file()
    assert (project / ".ade" / "mcp" / "catalog.json").is_file()

    skill_names = {item["name"] for item in SkillService(project).list()}
    assert "reservation-health" in skill_names

    agents = SubagentRegistry.discover(project).list()
    assert {item["name"] for item in agents} == {"snowflake-investigator"}

    blocked = plugins.evaluate(
        "tool.before",
        {
            "tool": "snowflake_mutation_execute",
            "environment": "prod",
            "args": {"sql": "DROP TABLE X"},
            "risk": "mutating",
        },
    )
    assert blocked.blocked is True
    assert "blocks production mutations" in blocked.reason


def test_bundle_hook_does_not_block_nonmatching_context(tmp_path):
    source = _bundle(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    service = PluginBundleService(project)
    service.install(source)
    plugins = PluginManager()
    service.activate("reservation-ops", plugins=plugins)

    allowed = plugins.evaluate(
        "tool.before",
        {
            "tool": "snowflake_mutation_execute",
            "environment": "dev",
            "args": {},
            "risk": "mutating",
        },
    )
    assert allowed.blocked is False


def test_bundle_rejects_contribution_path_escape(tmp_path):
    root = tmp_path / "bad"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    (root / "ade-plugin.yml").write_text(
        """name: bad-bundle
version: 1.0.0
description: Invalid bundle.
contributions:
  agents:
    - ../outside.md
"""
    )

    with pytest.raises(ValueError, match="contained"):
        PluginBundleService(tmp_path / "project").validate(root)


def test_bundle_install_is_collision_safe_by_default(tmp_path):
    source = _bundle(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    service = PluginBundleService(project)
    service.install(source)

    with pytest.raises(FileExistsError):
        service.install(source)
