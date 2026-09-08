from __future__ import annotations

from agentic_data_platform.training import TrainingStore


def test_training_ingest_search_context_status_and_dedup(tmp_path):
    store = TrainingStore(tmp_path / "training.db")
    first = store.ingest_text(
        "docs/architecture.md",
        "Snowflake RAW data is loaded by Airflow and transformed by dbt. "
        "The reservation mart depends on fact_reservation.",
    )
    assert first["status"] == "INDEXED"
    second = store.ingest_text(
        "docs/architecture.md",
        "Snowflake RAW data is loaded by Airflow and transformed by dbt. "
        "The reservation mart depends on fact_reservation.",
    )
    assert second["status"] == "UNCHANGED"

    results = store.search("reservation")
    assert results
    assert results[0]["source"] == "docs/architecture.md"
    context = store.context("reservation")
    assert context["chunks"]
    assert context["characters"] <= 12000
    status = store.status()
    assert status["documents"] == 1
    assert status["chunks"] >= 1


def test_training_project_ingest_is_bounded_and_refuses_secret_files(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "runbook.md").write_text("Run dbt build before deployment.")
    (tmp_path / ".env").write_text("SECRET=value")
    (tmp_path / "README.md").write_text("Hospitality platform")
    store = TrainingStore(tmp_path / "training.db")
    result = store.ingest_project(tmp_path)
    assert result["status"] == "PASS"
    sources = {item["source"] for item in result["results"] if "source" in item}
    assert "README.md" in sources
    assert ".env" not in sources


def test_training_file_outside_project_is_rejected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("not allowed")
    store = TrainingStore(tmp_path / "training.db")
    try:
        store.ingest_file(project, outside)
    except ValueError as exc:
        assert "outside project root" in str(exc)
    else:
        raise AssertionError("outside-project training file must be rejected")


def test_training_clear_removes_all_context(tmp_path):
    store = TrainingStore(tmp_path / "training.db")
    store.ingest_text("a.md", "dbt lineage quality")
    assert store.status()["documents"] == 1
    result = store.clear()
    assert result["documents"] == 0
    assert store.search("dbt") == []


def test_training_ingest_redacts_secret_values(tmp_path):
    store = TrainingStore(tmp_path / "training.db")
    store.ingest_text(
        "docs/private-runbook.md",
        "Bearer abcdefghijklmnopqrstuvwxyz123456\nreservation pipeline",
    )
    results = store.search("reservation")
    assert results
    content = "\n".join(str(item["content"]) for item in results)
    assert "abcdefghijklmnopqrstuvwxyz123456" not in content
    assert "[REDACTED]" in content
