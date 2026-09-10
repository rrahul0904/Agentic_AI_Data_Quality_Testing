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

__all__ = [
    "ADESearchEngine",
    "ADESearchIndex",
    "CortexSearchBackend",
    "DeterministicHashEmbedding",
    "EmbeddingProvider",
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
