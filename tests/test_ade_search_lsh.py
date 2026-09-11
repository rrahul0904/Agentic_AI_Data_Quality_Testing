from __future__ import annotations

from agentic_data_platform.retrieval import ADESearchIndex, RetrievalQuery, SearchChunk


class TopicEmbedding:
    name = "topic-semantic-test-v1"

    def embed(self, text):
        value = text.casefold()
        if "workflow" in value or "orchestration" in value or "scheduler" in value:
            return [1.0, 0.0, 0.0, 0.0]
        if "revenue" in value or "invoice" in value or "finance" in value:
            return [0.0, 1.0, 0.0, 0.0]
        if "warehouse" in value or "snowflake" in value:
            return [0.0, 0.0, 1.0, 0.0]
        return [0.0, 0.0, 0.0, 1.0]


def test_large_index_uses_persisted_lsh_candidates_then_exact_cosine(tmp_path):
    index = ADESearchIndex(
        tmp_path / "search.db",
        index_name="scale",
        embedder=TopicEmbedding(),
        exact_vector_scan_limit=2,
        lsh_tables=6,
        lsh_bits=8,
        lsh_candidate_limit=50,
    )
    chunks = [
        SearchChunk("workflow", "airflow.md", "Orchestration scheduler recovery policy."),
        SearchChunk("finance", "finance.md", "Revenue invoice recognition guidance."),
        SearchChunk("warehouse", "warehouse.md", "Snowflake warehouse sizing runbook."),
        SearchChunk("other-1", "misc-1.md", "Customer support handbook."),
        SearchChunk("other-2", "misc-2.md", "Application deployment checklist."),
    ]
    assert index.upsert_many(chunks)["INSERTED"] == len(chunks)

    hits = index.search(
        RetrievalQuery("workflow", limit=3),
        lexical_weight=0.0,
        vector_weight=1.0,
        rerank_weight=0.0,
    )
    assert hits
    assert hits[0].source == "airflow.md"
    assert hits[0].evidence["embedding_provider"] == TopicEmbedding.name
    assert hits[0].evidence["vector_candidate_strategy"] == "sqlite_lsh_approximate"
    assert 0 < hits[0].evidence["vector_candidates_scored"] <= 50
    assert hits[0].evidence["scoring"]["cosine"] == 1.0

    stats = index.stats()
    assert stats["vector_candidates"]["large_index_strategy"] == "sqlite_lsh_approximate"
    assert stats["vector_candidates"]["persisted_lsh_rows"] == len(chunks) * 6


def test_lsh_rows_are_replaced_and_removed_with_chunk_lifecycle(tmp_path):
    index = ADESearchIndex(
        tmp_path / "lifecycle.db",
        index_name="ops",
        embedder=TopicEmbedding(),
        exact_vector_scan_limit=0,
        lsh_tables=4,
        lsh_bits=6,
        lsh_candidate_limit=20,
    )
    original = SearchChunk("one", "runbook.md", "Orchestration scheduler guide")
    assert index.upsert(original).status == "INSERTED"
    assert index.stats()["vector_candidates"]["persisted_lsh_rows"] == 4

    changed = SearchChunk("one", "runbook.md", "Revenue invoice guide")
    assert index.upsert(changed).status == "UPDATED"
    assert index.stats()["vector_candidates"]["persisted_lsh_rows"] == 4

    assert index.delete("one").status == "DELETED"
    assert index.stats()["vector_candidates"]["persisted_lsh_rows"] == 0