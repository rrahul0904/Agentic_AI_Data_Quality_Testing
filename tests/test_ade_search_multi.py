from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api import create_app
from agentic_data_platform.retrieval import ADESearchEngine, ADESearchIndex, RetrievalQuery, SearchChunk


def test_multi_index_boosts_are_applied_and_explained(tmp_path):
    database = tmp_path / "search.db"
    operations = ADESearchIndex(database, index_name="operations")
    documents = ADESearchIndex(database, index_name="documents")
    operations.upsert(SearchChunk("ops", "ops.md", "scheduler recovery policy", {"kind": "ops"}))
    documents.upsert(SearchChunk("docs", "docs.md", "scheduler architecture guide", {"kind": "docs"}))

    engine = ADESearchEngine({"operations": operations, "documents": documents})
    result = engine.search(
        RetrievalQuery("scheduler", limit=2),
        index_boosts={"operations": 1.0, "documents": 5.0},
        rerank_weight=0.0,
        metadata_weight=0.0,
    )
    assert [hit.source for hit in result.hits] == ["docs.md", "ops.md"]
    explanation = result.hits[0].evidence["multi_index"]
    assert explanation["fusion"] == "weighted_reciprocal_rank"
    assert explanation["index_boosts"] == {"documents": 5.0}
    assert explanation["index_contributions"]["documents"] > 0


def test_multi_index_api_is_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_DEMO_PROJECT", str(tmp_path))
    client = TestClient(create_app())
    for payload in (
        {
            "index_name": "operations",
            "chunk_id": "ops",
            "source": "ops.md",
            "content": "scheduler recovery policy",
            "metadata": {"priority": 1},
        },
        {
            "index_name": "documents",
            "chunk_id": "docs",
            "source": "docs.md",
            "content": "scheduler architecture guide",
            "metadata": {"priority": 9},
        },
    ):
        response = client.post("/api/v1/search/index", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "PASS"

    response = client.post(
        "/api/v1/search/multi-query",
        json={
            "query": "scheduler",
            "index_names": ["operations", "documents"],
            "limit": 2,
            "index_boosts": {"documents": 4.0},
            "numeric_boosts": [
                {"field": "priority", "minimum": 0, "maximum": 10, "weight": 1.0}
            ],
            "fusion_weight": 0.6,
            "rerank_weight": 0.0,
            "metadata_weight": 0.4,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "PASS"
    assert body["backend"] == "ade_search_multi_index"
    assert body["index_names"] == ["operations", "documents"]
    assert body["results"][0]["source"] == "docs.md"
    evidence = body["results"][0]["evidence"]["multi_index"]
    assert evidence["metadata_profile"]["numeric_boosts"][0]["field"] == "priority"
