from __future__ import annotations

from agentic_data_platform.memory import MemoryStore
from agentic_data_platform.training.learned import (
    import_markdown,
    list_entries,
    parse_markdown_sections,
    remove_entry,
    save_entry,
)


def test_named_training_save_update_list_remove_and_budget(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    saved = save_entry(
        store,
        kind="rule",
        name="No FLOAT",
        content="Never use FLOAT for financial columns.",
        scope="project",
        project_id="hotel",
        source="user correction",
        citations=["docs/sql.md#types"],
    )
    assert saved["action"] == "saved"
    training_id = saved["training_id"]

    store.mark_training_applied(training_id)
    updated = save_entry(
        store,
        kind="rule",
        name="no-float",
        content="Never use FLOAT for money; use fixed precision NUMBER.",
        scope="project",
        project_id="hotel",
    )
    assert updated["action"] == "updated"
    assert updated["training_id"] == training_id
    assert updated["applied_count"] == 1

    listed = list_entries(
        store,
        kind="rule",
        scope="project",
        project_id="hotel",
    )
    assert listed["count"] == 1
    assert listed["entries"][0]["name"] == "no-float"
    assert listed["entries"][0]["applied_count"] == 1
    assert listed["counts"]["rule"] == 1
    assert listed["budget"]["budget"] == 48000

    removed = remove_entry(
        store,
        kind="rule",
        name="no-float",
        scope="project",
        project_id="hotel",
    )
    assert removed["action"] == "removed"
    assert list_entries(
        store,
        scope="project",
        project_id="hotel",
    )["count"] == 0


def test_markdown_training_import_preview_and_apply(tmp_path):
    path = tmp_path / "standards.md"
    path.write_text(
        "# SQL Standards\n\n"
        "## Staging Models\n"
        "Use one source per staging model.\n\n"
        "## Financial Types\n"
        "Use NUMBER(18,2) for money.\n"
    )
    sections = parse_markdown_sections(path.read_text())
    assert [item["name"] for item in sections] == [
        "staging-models",
        "financial-types",
    ]
    assert sections[0]["content"].startswith("Context: SQL Standards")

    store = MemoryStore(tmp_path / "training.db")
    preview = import_markdown(
        store,
        path,
        kind="standard",
        scope="project",
        project_id="hotel",
        dry_run=True,
    )
    assert preview["status"] == "PASS"
    assert preview["count"] == 2
    assert list_entries(store, project_id="hotel")["count"] == 0

    applied = import_markdown(
        store,
        path,
        kind="standard",
        scope="project",
        project_id="hotel",
        dry_run=False,
    )
    assert applied["count"] == 2
    assert list_entries(
        store,
        kind="standard",
        scope="project",
        project_id="hotel",
    )["count"] == 2
