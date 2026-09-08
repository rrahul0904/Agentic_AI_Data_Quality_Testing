from __future__ import annotations

from agentic_data_platform.skills import SkillService


def test_custom_skill_create_test_disable_enable(tmp_path):
    service = SkillService(tmp_path, state_path=tmp_path / ".ade" / "skills.db")
    created = service.create(
        "warehouse-audit",
        "Audit warehouse metadata",
        "Use deterministic warehouse tools.",
        apply_paths=("models/**/*.sql",),
    )
    assert created["status"] == "CREATED"
    assert service.test("warehouse-audit")["status"] == "PASS"
    assert service.set_enabled("warehouse-audit", False)["enabled"] is False
    assert service.set_enabled("warehouse-audit", True)["enabled"] is True


def test_local_skill_source_install(tmp_path):
    source_root = tmp_path / "source"
    skill_dir = source_root / "custom-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: custom-skill\n"
        "description: Custom local skill\n"
        "alwaysApply: false\n"
        "---\n\n"
        "Use deterministic evidence.\n"
    )

    project = tmp_path / "project"
    project.mkdir()
    service = SkillService(project, state_path=project / ".ade" / "skills.db")
    result = service.install_source(str(source_root))
    assert result["status"] == "INSTALLED"
    assert result["count"] == 1
    assert service.inspect("custom-skill")["enabled"] is True
    assert service.test("custom-skill")["status"] == "PASS"


def test_remote_skill_install_rejects_non_github_urls(tmp_path):
    service = SkillService(tmp_path, state_path=tmp_path / "skills.db")
    try:
        service.install_source("https://example.com/not-allowed.git")
    except ValueError as exc:
        assert "github.com" in str(exc)
    else:
        raise AssertionError("non-GitHub remote skill source must be rejected")
