from agentic_data_platform.skills import SkillRegistry, parse_skill


def test_skill_discovery_and_apply_paths(tmp_path):
    skill_dir = tmp_path / ".opencode" / "skills" / "dbt-test"
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\n"
        "name: dbt-test\n"
        "description: Test dbt models\n"
        "alwaysApply: false\n"
        "applyPaths:\n"
        "  - dbt_project.yml\n"
        "---\n\n"
        "Run dbt tests."
    )
    (tmp_path / "dbt_project.yml").write_text("name: demo")
    registry = SkillRegistry.discover(tmp_path)
    skill = registry.get("dbt-test")
    assert skill.description == "Test dbt models"
    assert skill.body == "Run dbt tests."
    assert [item.name for item in registry.auto_load(tmp_path)] == ["dbt-test"]


def test_always_apply_and_no_cross_project_scan(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    global_root = tmp_path / "global-skills"
    skill_dir = global_root / "always"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: always\ndescription: Always apply\nalwaysApply: true\n---\nBody"
    )
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "dbt_project.yml").write_text("name: unrelated")
    registry = SkillRegistry.discover(project, global_root=global_root)
    assert [item.name for item in registry.auto_load(project)] == ["always"]


def test_skill_create_parse_and_remove(tmp_path):
    registry = SkillRegistry()
    root = tmp_path / "skills"
    path = registry.create(
        root,
        "sql-review",
        "Review SQL",
        "Use deterministic SQL tools.",
        apply_paths=["models/**/*.sql"],
    )
    parsed = parse_skill(path)
    assert parsed.name == "sql-review"
    assert parsed.apply_paths == ("models/**/*.sql",)
    assert registry.remove("sql-review", delete_file=True) is True
    assert not path.exists()
