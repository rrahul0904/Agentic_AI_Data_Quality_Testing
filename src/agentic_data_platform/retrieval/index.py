"""Persistent, provider-neutral ADE Search index.

The local implementation intentionally uses only SQLite + Python so it can run inside a
laptop, Docker container, Kubernetes pod, or private VPC. Embeddings are pluggable; the
default hashing embedder is deterministic/offline and must not be described as a learned
semantic model. Production deployments can inject a learned embedding provider or swap the
storage adapter without changing the search/evidence contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Protocol, Sequence

from .backends import RetrievalHit, RetrievalQuery


_TOKEN = re.compile(r"[A-Za-z0-9_]+")


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, text: str) -> Sequence[float]: ...


class DeterministicHashEmbedding:
    """Bounded offline hashing vectors for deterministic local retrieval.

    This is a lexical feature projection, not an ML embedding model. It provides a zero-cost
    vector lane and a stable interface for learned embedding providers.
    """

    name = "deterministic_hash_v1"

    def __init__(self, dimensions: int = 192) -> None:
        if dimensions < 32 or dimensions > 4096:
            raise ValueError("dimensions must be between 32 and 4096")
        self.dimensions = int(dimensions)

    def embed(self, text: str) -> Sequence[float]:
        vector = [0.0] * self.dimensions
        for token in _TOKEN.findall(text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


@dataclass(frozen=True)
class SearchChunk:
    chunk_id: str
    source: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.chunk_id.strip():
            raise ValueError("chunk_id is required")
        if not self.source.strip():
            raise ValueError("source is required")
        if not self.content.strip():
            raise ValueError("content is required")
        if len(self.content) > 1_000_000:
            raise ValueError("chunk content exceeds 1,000,000 characters")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IndexMutation:
    status: str
    chunk_id: str
    content_hash: str | None = None


class ADESearchIndex:
    """SQLite FTS5 + vector hybrid index with incremental content hashes."""

    backend_name = "ade_search"

    def __init__(
        self,
        database: str | Path,
        *,
        index_name: str = "default",
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        if not index_name.strip():
            raise ValueError("index_name is required")
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.index_name = index_name.strip()
        self.embedder = embedder or DeterministicHashEmbedding()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ade_search_chunks (
                    index_name TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (index_name, chunk_id)
                )
                """
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS ade_search_fts USING fts5(
                    index_name UNINDEXED,
                    chunk_id UNINDEXED,
                    content,
                    tokenize='unicode61'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ade_search_source ON ade_search_chunks(index_name, source)"
            )

    @staticmethod
    def _metadata_json(metadata: Mapping[str, Any]) -> str:
        return json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"), default=str)

    def upsert(self, chunk: SearchChunk) -> IndexMutation:
        chunk.validate()
        content_hash = chunk.content_hash
        metadata_json = self._metadata_json(chunk.metadata)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT content_hash, metadata_json, source, embedding_provider FROM ade_search_chunks "
                "WHERE index_name=? AND chunk_id=?",
                (self.index_name, chunk.chunk_id),
            ).fetchone()
            if (
                current
                and current["content_hash"] == content_hash
                and current["metadata_json"] == metadata_json
                and current["source"] == chunk.source
                and current["embedding_provider"] == self.embedder.name
            ):
                return IndexMutation("NOOP", chunk.chunk_id, content_hash)

            embedding = [float(value) for value in self.embedder.embed(chunk.content)]
            connection.execute(
                """
                INSERT INTO ade_search_chunks(
                    index_name, chunk_id, source, content, content_hash, metadata_json,
                    embedding_json, embedding_provider, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(index_name, chunk_id) DO UPDATE SET
                    source=excluded.source,
                    content=excluded.content,
                    content_hash=excluded.content_hash,
                    metadata_json=excluded.metadata_json,
                    embedding_json=excluded.embedding_json,
                    embedding_provider=excluded.embedding_provider,
                    updated_at=excluded.updated_at
                """,
                (
                    self.index_name,
                    chunk.chunk_id,
                    chunk.source,
                    chunk.content,
                    content_hash,
                    metadata_json,
                    json.dumps(embedding, separators=(",", ":")),
                    self.embedder.name,
                    now,
                ),
            )
            connection.execute(
                "DELETE FROM ade_search_fts WHERE index_name=? AND chunk_id=?",
                (self.index_name, chunk.chunk_id),
            )
            connection.execute(
                "INSERT INTO ade_search_fts(index_name, chunk_id, content) VALUES (?, ?, ?)",
                (self.index_name, chunk.chunk_id, chunk.content),
            )
        return IndexMutation("UPDATED" if current else "INSERTED", chunk.chunk_id, content_hash)

    def upsert_many(self, chunks: Sequence[SearchChunk]) -> dict[str, int]:
        counts = {"INSERTED": 0, "UPDATED": 0, "NOOP": 0}
        seen: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_id in seen:
                raise ValueError(f"duplicate chunk_id in batch: {chunk.chunk_id}")
            seen.add(chunk.chunk_id)
            mutation = self.upsert(chunk)
            counts[mutation.status] += 1
        return counts

    def delete(self, chunk_id: str) -> IndexMutation:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM ade_search_chunks WHERE index_name=? AND chunk_id=?",
                (self.index_name, chunk_id),
            ).fetchone()
            if not row:
                return IndexMutation("NOOP", chunk_id)
            connection.execute(
                "DELETE FROM ade_search_chunks WHERE index_name=? AND chunk_id=?",
                (self.index_name, chunk_id),
            )
            connection.execute(
                "DELETE FROM ade_search_fts WHERE index_name=? AND chunk_id=?",
                (self.index_name, chunk_id),
            )
        return IndexMutation("DELETED", chunk_id, row["content_hash"])

    def delete_source(self, source: str) -> int:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT chunk_id FROM ade_search_chunks WHERE index_name=? AND source=?",
                (self.index_name, source),
            ).fetchall()
            ids = [row["chunk_id"] for row in rows]
            if ids:
                connection.executemany(
                    "DELETE FROM ade_search_chunks WHERE index_name=? AND chunk_id=?",
                    [(self.index_name, chunk_id) for chunk_id in ids],
                )
                connection.executemany(
                    "DELETE FROM ade_search_fts WHERE index_name=? AND chunk_id=?",
                    [(self.index_name, chunk_id) for chunk_id in ids],
                )
        return len(ids)

    @staticmethod
    def _matches_filter(metadata: Mapping[str, Any], filters: Mapping[str, Any] | None) -> bool:
        if not filters:
            return True
        for key, expected in filters.items():
            actual = metadata.get(key)
            if isinstance(expected, Mapping):
                if "eq" in expected and actual != expected["eq"]:
                    return False
                if "in" in expected and actual not in expected["in"]:
                    return False
                if "gte" in expected and (actual is None or actual < expected["gte"]):
                    return False
                if "lte" in expected and (actual is None or actual > expected["lte"]):
                    return False
            elif isinstance(expected, (list, tuple, set, frozenset)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right):
            return 0.0
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)

    @staticmethod
    def _fts_query(text: str) -> str:
        tokens = _TOKEN.findall(text)
        if not tokens:
            raise ValueError("search query contains no searchable tokens")
        return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens[:64])

    def _rows(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM ade_search_chunks WHERE index_name=?",
                (self.index_name,),
            ).fetchall()

    def search(
        self,
        request: RetrievalQuery,
        *,
        lexical_weight: float = 0.45,
        vector_weight: float = 0.45,
        rerank_weight: float = 0.10,
        explain: bool = True,
    ) -> list[RetrievalHit]:
        request.validate()
        weights = (float(lexical_weight), float(vector_weight), float(rerank_weight))
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("search weights must be non-negative with a positive sum")
        total_weight = sum(weights)
        lexical_weight, vector_weight, rerank_weight = (weight / total_weight for weight in weights)
        candidate_limit = max(50, min(1000, request.bounded_limit() * 12))

        lexical: dict[str, tuple[float, int]] = {}
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    "SELECT chunk_id, bm25(ade_search_fts) AS rank_score FROM ade_search_fts "
                    "WHERE ade_search_fts MATCH ? AND index_name=? ORDER BY rank_score LIMIT ?",
                    (self._fts_query(request.query), self.index_name, candidate_limit),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                raise RuntimeError("SQLite FTS5 is required for ADE Search") from exc
        for rank, row in enumerate(rows, 1):
            raw = float(row["rank_score"])
            lexical[row["chunk_id"]] = (1.0 / (1.0 + abs(raw)), rank)

        query_embedding = [float(value) for value in self.embedder.embed(request.query)]
        query_tokens = set(token.casefold() for token in _TOKEN.findall(request.query))
        candidates: list[dict[str, Any]] = []
        for row in self._rows():
            metadata = json.loads(row["metadata_json"] or "{}")
            if not self._matches_filter(metadata, request.filters):
                continue
            embedding = json.loads(row["embedding_json"])
            cosine = self._cosine(query_embedding, embedding)
            vector_score = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
            lexical_score, lexical_rank = lexical.get(row["chunk_id"], (0.0, 0))
            content_tokens = set(token.casefold() for token in _TOKEN.findall(row["content"]))
            overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens))
            final = (
                lexical_weight * lexical_score
                + vector_weight * vector_score
                + rerank_weight * overlap
            )
            if final <= 0:
                continue
            candidates.append(
                {
                    "row": row,
                    "metadata": metadata,
                    "lexical_score": lexical_score,
                    "lexical_rank": lexical_rank,
                    "vector_score": vector_score,
                    "cosine": cosine,
                    "rerank_score": overlap,
                    "final_score": final,
                }
            )

        candidates.sort(
            key=lambda item: (-item["final_score"], -item["lexical_score"], item["row"]["chunk_id"])
        )
        hits: list[RetrievalHit] = []
        for rank, item in enumerate(candidates[: request.bounded_limit()], 1):
            row = item["row"]
            evidence = {
                "index_name": self.index_name,
                "rank": rank,
                "content_hash": row["content_hash"],
                "embedding_provider": row["embedding_provider"],
                "updated_at": row["updated_at"],
            }
            if explain:
                evidence["scoring"] = {
                    "lexical": round(item["lexical_score"], 8),
                    "lexical_rank": item["lexical_rank"] or None,
                    "vector": round(item["vector_score"], 8),
                    "cosine": round(item["cosine"], 8),
                    "rerank_overlap": round(item["rerank_score"], 8),
                    "weights": {
                        "lexical": lexical_weight,
                        "vector": vector_weight,
                        "rerank": rerank_weight,
                    },
                    "final": round(item["final_score"], 8),
                }
            hits.append(
                RetrievalHit(
                    backend=self.backend_name,
                    source=row["source"],
                    content=row["content"],
                    score=float(item["final_score"]),
                    fields={"chunk_id": row["chunk_id"], "metadata": item["metadata"]},
                    evidence=evidence,
                )
            )
        return hits

    def stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS chunks, COUNT(DISTINCT source) AS sources, "
                "MAX(updated_at) AS last_updated FROM ade_search_chunks WHERE index_name=?",
                (self.index_name,),
            ).fetchone()
        return {
            "backend": self.backend_name,
            "index_name": self.index_name,
            "chunks": int(row["chunks"]),
            "sources": int(row["sources"]),
            "last_updated": row["last_updated"],
            "embedding_provider": self.embedder.name,
            "database": str(self.database),
        }
