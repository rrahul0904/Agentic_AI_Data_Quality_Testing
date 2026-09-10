"""Provider-neutral retrieval for ADE project and warehouse knowledge."""

from .backends import (
    CortexSearchBackend,
    HybridRetrievalBackend,
    LocalProjectRetrievalBackend,
    RetrievalHit,
    RetrievalQuery,
)
from .engine import ADESearchEngine, MultiIndexSearchResult, Reranker, TokenOverlapReranker
from .index import (
    ADESearchIndex,
    DeterministicHashEmbedding,
    EmbeddingProvider,
    IndexMutation,
    SearchChunk,
)
from .providers import HTTPEmbeddingProvider, HTTPReranker

__all__ = [
    "ADESearchEngine",
    "ADESearchIndex",
    "CortexSearchBackend",
    "DeterministicHashEmbedding",
    "EmbeddingProvider",
    "HTTPEmbeddingProvider",
    "HTTPReranker",
    "HybridRetrievalBackend",
    "IndexMutation",
    "LocalProjectRetrievalBackend",
    "MultiIndexSearchResult",
    "Reranker",
    "RetrievalHit",
    "RetrievalQuery",
    "SearchChunk",
    "TokenOverlapReranker",
]
