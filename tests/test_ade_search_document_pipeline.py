from __future__ import annotations

from agentic_data_platform.knowledge import DocumentExtraction, DocumentIntelligencePipeline
from agentic_data_platform.retrieval import ADESearchIndex, RetrievalQuery, SearchChunk


def test_ade_search_is_incremental_filtered_explainable_and_namespace_isolated(tmp_path):
    database = tmp_path / "search.db"
    index = ADESearchIndex(database, index_name="operations")
    first = SearchChunk(
        "runbook-1",
        "runbook.md",
        "Airflow scheduler memory pressure can kill queued tasks.",
        {"environment": "prod", "system": "airflow"},
    )
    second = SearchChunk(
        "model-1",
        "model.sql",
        "Marketing campaign revenue attribution model.",
        {"environment": "dev", "system": "dbt"},
    )

    assert index.upsert(first).status == "INSERTED"
    assert index.upsert(second).status == "INSERTED"
    assert index.upsert(first).status == "NOOP"

    updated = SearchChunk(
        "runbook-1",
        "runbook.md",
        "Airflow scheduler memory pressure can kill workers and queued tasks.",
        {"environment": "prod", "system": "airflow"},
    )
    assert index.upsert(updated).status == "UPDATED"

    hits = index.search(
        RetrievalQuery("scheduler memory", limit=5, filters={"environment": "prod"})
    )
    assert hits
    assert hits[0].source == "runbook.md"
    assert hits[0].backend == "ade_search"
    assert hits[0].fields["metadata"]["system"] == "airflow"
    assert hits[0].evidence["content_hash"] == updated.content_hash
    assert hits[0].evidence["scoring"]["lexical"] > 0
    assert hits[0].evidence["scoring"]["final"] > 0
    assert len(hits[0].fingerprint) == 64
    assert index.stats()["chunks"] == 2

    isolated = ADESearchIndex(database, index_name="other")
    assert isolated.search(RetrievalQuery("scheduler", limit=5)) == []


def test_document_pipeline_redacts_chunks_indexes_and_noops_unchanged_content(tmp_path):
    index = ADESearchIndex(tmp_path / "knowledge.db", index_name="documents")
    pipeline = DocumentIntelligencePipeline(index)
    content = (
        b"# Production Runbook\n\n"
        b"Airflow scheduler memory pressure caused worker restarts.\n\n"
        b"password=hunter2"
    )

    processed = pipeline.process(
        "runbook.md",
        content,
        index_metadata={"environment": "prod", "system": "airflow"},
    )
    assert processed.index_status["status"] == "PASS"
    assert processed.blocks[0].kind == "heading"
    assert processed.metadata["secrets_redacted"] is True
    assert all("hunter2" not in block.text for block in processed.blocks)
    assert any("[REDACTED]" in block.text for block in processed.blocks)

    hits = index.search(
        RetrievalQuery("worker restarts", limit=3, filters={"environment": "prod"})
    )
    assert hits
    assert hits[0].source == "runbook.md"
    assert hits[0].fields["metadata"]["document_id"] == processed.document_id
    assert hits[0].fields["metadata"]["secrets_redacted"] is True

    repeated = pipeline.process(
        "runbook.md",
        content,
        index_metadata={"environment": "prod", "system": "airflow"},
    )
    assert repeated.index_status["status"] == "NOOP"
    assert index.stats()["sources"] == 1


def test_document_pipeline_can_use_explicit_ocr_provider(tmp_path):
    class FakeOCR:
        name = "fake-ocr"

        def extract(self, filename, content, *, content_type=None):
            assert content == b"not-a-real-png"
            return DocumentExtraction(
                source=filename,
                source_type="png",
                text="Invoice number INV-99 total 42.00",
                metadata={"content_type": content_type, "pages": 1},
            )

    pipeline = DocumentIntelligencePipeline()
    processed = pipeline.process(
        "invoice.png",
        b"not-a-real-png",
        content_type="image/png",
        ocr_provider=FakeOCR(),
    )
    assert processed.provenance["ocr_used"] is True
    assert processed.provenance["parser"] == "ocr:fake-ocr"
    assert processed.blocks[0].confidence == 1.0
    assert "INV-99" in processed.chunks[0].text
