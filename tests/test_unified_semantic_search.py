from __future__ import annotations

import sqlite3

from agentic_data_platform.connectors.sqlite import SQLiteConnector
from agentic_data_platform.metadata.service import MetadataService
from agentic_data_platform.search import SearchDocument, UnifiedSemanticIndex


def test_hybrid_search_finds_conceptually_related_code_without_exact_query(tmp_path):
    root = tmp_path / "project"
    (root / "models").mkdir(parents=True)
    (root / "models" / "mart_billing.sql").write_text(
        "select hotel_id, sum(amount) as gross_sales from payments group by 1"
    )
    (root / "dags").mkdir()
    (root / "dags" / "booking_pipeline.py").write_text(
        "def load_bookings():\n    return 'reservation ingestion'\n"
    )

    index = UnifiedSemanticIndex(tmp_path / "search.db")
    indexed = index.index_project(root)
    assert indexed["status"] == "PASS"
    assert indexed["files_indexed"] == 2

    result = index.search("where is hotel revenue calculated?", mode="hybrid")
    assert result["status"] == "PASS"
    assert result["embedding_backend"] == "local_private"
    assert result["results"]
    assert result["results"][0]["path"] == "models/mart_billing.sql"


def test_search_spans_project_and_warehouse_metadata(tmp_path):
    source = sqlite3.connect(":memory:")
    source.execute(
        "CREATE TABLE reservations(reservation_id INTEGER, guest_id INTEGER, amount REAL)"
    )
    metadata = MetadataService(tmp_path / "metadata.db")
    metadata.refresh("warehouse", SQLiteConnector(source), schemas=["main"])

    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("Bookings are transformed into guest stay metrics.")

    index = UnifiedSemanticIndex(tmp_path / "search.db")
    index.index_project(root)
    result = index.index_metadata(metadata, connection_name="warehouse")
    assert result["objects_indexed"] == 1

    search = index.search("booking reservation amount")
    kinds = {item["kind"] for item in search["results"]}
    assert "warehouse_object" in kinds
    assert "documentation" in kinds


def test_external_embedding_backend_can_be_used_without_changing_search_contract(tmp_path):
    def embed(text: str):
        lowered = text.casefold()
        return [
            float("revenue" in lowered or "billing" in lowered),
            float("airflow" in lowered or "dag" in lowered),
        ]

    index = UnifiedSemanticIndex(tmp_path / "search.db", embedding_fn=embed)
    index.upsert(SearchDocument(
        "d1",
        "code",
        "project",
        "billing model",
        "collect customer payments",
        path="billing.py",
    ))
    index.upsert(SearchDocument(
        "d2",
        "airflow",
        "project",
        "scheduler",
        "airflow dag retry logic",
        path="dags/retry.py",
    ))

    result = index.search("revenue", mode="semantic")
    assert result["embedding_backend"] == "external"
    assert result["results"][0]["document_id"] == "d1"


def test_search_supports_kind_filter_and_bounded_results(tmp_path):
    index = UnifiedSemanticIndex(tmp_path / "search.db")
    index.upsert(SearchDocument("a", "code", "project", "reservation code", "booking logic"))
    index.upsert(SearchDocument("b", "documentation", "project", "reservation docs", "booking rules"))

    result = index.search("reservation", kinds=["documentation"], limit=1)
    assert result["result_count"] == 1
    assert result["results"][0]["kind"] == "documentation"
