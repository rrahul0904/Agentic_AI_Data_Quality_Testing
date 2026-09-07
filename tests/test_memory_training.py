from agentic_data_platform.memory import MemoryStore


def test_memory_deduplicates_searches_and_expires(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    first = store.save_memory(
        "fact_reservation grain is reservation_id",
        project_id="hotel",
        tags=["dbt", "grain"],
        citations=["architecture.md"],
    )
    second = store.save_memory(
        "fact_reservation grain is reservation_id",
        project_id="hotel",
        tags=["dbt"],
    )
    assert first == second
    found = store.search("reservation", project_id="hotel")
    assert found and found[0]["memory_id"] == first
    assert "architecture.md" in found[0]["citations"]
    assert store.remove_memory(first) is True
    assert store.search("reservation", project_id="hotel") == []


def test_training_tracks_source_citations_and_application(tmp_path):
    store = MemoryStore(tmp_path / "training.db")
    training_id = store.save_training(
        "standard",
        "All marts require owner metadata",
        project_id="hotel",
        source="architecture.md",
        citations=["architecture.md#ownership"],
    )
    duplicate = store.save_training(
        "standard",
        "All marts require owner metadata",
        project_id="hotel",
        source="architecture.md",
    )
    assert training_id == duplicate
    store.mark_training_applied(training_id)
    item = store.list_training(project_id="hotel")[0]
    assert item["applied_count"] == 1
    assert item["source"] == "architecture.md"
    assert item["citations"] == ["architecture.md#ownership"]
    assert store.remove_training(training_id) is True
