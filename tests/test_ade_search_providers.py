from __future__ import annotations

import pytest

from agentic_data_platform.retrieval import HTTPEmbeddingProvider, HTTPReranker, RetrievalHit


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def test_http_embedding_provider_is_vendor_neutral_bounded_and_testable():
    client = FakeClient({"data": [{"embedding": [0.25, -0.5, 1.0]}]})
    provider = HTTPEmbeddingProvider(
        "http://localhost:8080/v1/embeddings",
        "local-embed-model",
        client=client,
    )
    assert provider.embed("scheduler retry policy") == [0.25, -0.5, 1.0]
    url, request = client.calls[0]
    assert url.endswith("/v1/embeddings")
    assert request["json"] == {"model": "local-embed-model", "input": "scheduler retry policy"}
    assert provider.name == "http_embedding:local-embed-model"

    with pytest.raises(ValueError):
        HTTPEmbeddingProvider("http://remote.example/v1/embeddings", "model")


def test_http_reranker_accepts_common_score_shapes():
    client = FakeClient({"results": [{"relevance_score": 0.87}]})
    reranker = HTTPReranker(
        "http://127.0.0.1:8081/rerank",
        "local-reranker",
        client=client,
    )
    hit = RetrievalHit(
        backend="test",
        source="runbook.md",
        content="Airflow scheduler retry policy",
        score=0.2,
    )
    assert reranker.score("scheduler policy", hit) == 0.87
    _, request = client.calls[0]
    assert request["json"]["documents"] == [hit.content]
