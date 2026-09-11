"""Persistent, provider-neutral ADE Search index.

The local implementation intentionally uses only SQLite + Python so it can run inside a
laptop, Docker container, Kubernetes pod, or private VPC. Embeddings are pluggable; the
default hashing embedder is deterministic/offline and must not be described as a learned
semantic model. Production deployments can inject a learned embedding provider or swap the
storage adapter without changing the search/evidence contract.

Small indexes use exact vector candidate scans. Larger local indexes use persisted
multi-table random-hyperplane LSH for approximate candidate generation, followed by exact
cosine scoring on the bounded candidate set. This is explicitly not HNSW and should not be
presented as an exact nearest-neighbor index.
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
    """SQLite FTS5 + pluggable-vector hybrid index with local approximate candidates."""

    backend_name = "ade_search"

    def __init__(
        self,
        database: str | Path,
        *,
        index_name: str = "default",
        embedder: EmbeddingProvider | None = None,
        exact_vector_scan_limit: int = 5_000,
        lsh_tables: int = 4,
        lsh_bits: int = 12,
        lsh_candidate_limit: int = 2_000,
    ) -> None:
        if not index_name.strip():
            raise ValueError("index_name is required")
        if exact_vector_scan_limit < 0:
            raise ValueError("exact_vector_scan_limit must be non-negative")
        if lsh_tables < 1 or lsh_tables > 32:
            raise ValueError("lsh_tables must be between 1 and 32")
        if lsh_bits < 4 or lsh_bits > 24:
            raise ValueError("lsh_bits must be between 4 and 24")
        if lsh_candidate_limit < 10 or lsh_candidate_limit > 100_000:
            raise ValueError("lsh_candidate_limit must be between 10 and 100000")
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.index_name = index_name.strip()
        self.embedder = embedder or DeterministicHashEmbedding()
        self.exact_vector_scan_limit = int(exact_vector_scan_limit)
        self.lsh_tables = int(lsh_tables)
        self.lsh_bits = int(lsh_bits)
        self.lsh_candidate_limit = int(lsh_candidate_limit)
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
                """
                CREATE TABLE IF NOT EXISTS ade_search_lsh (
                    index_name TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    table_no INTEGER NOT NULL,
                    bucket INTEGER NOT NULL,
                    PRIMARY KEY(index_name, chunk_id, embedding_provider, table_no)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ade_search_source ON ade_search_chunks(index_name, source)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ade_search_lsh_bucket "
                "ON ade_search_lsh(index_name, embedding_provider, table_no, bucket)"
            )

    @staticmethod
    def _metadata_json(metadata: Mapping[str, Any]) -> str:
        return json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _hyperplane_sign(table_no: int, bit_no: int, dimension: int) -> float:
        digest = hashlib.sha256(f"ade-lsh-v1:{table_no}:{bit_no}:{dimension}".encode("utf-8")).digest()
        return 1.0 if digest[0] & 1 else -1.0

    def _lsh_buckets(self, embedding: Sequence[float]) -> tuple[int, ...]:
        buckets: list[int] = []
        for table_no in range(self.lsh_tables):
            bucket = 0
            for bit_no in range(self.lsh_bits):
                projection = 0.0
                for dimension, value in enumerate(embedding):
                    projection += float(value) * self._hyperplane_sign(table_no, bit_no, dimension)
                if projection >= 0.0:
                    bucket |= 1 << bit_no
            buckets.append(bucket)
        return tuple(buckets)

    def _write_lsh(
        self,
        connection: sqlite3.Connection,
        chunk_id: str,
        embedding: Sequence[float],
        provider: str,
    ) -> None:
        connection.execute(
            "DELETE FROM ade_search_lsh WHERE index_name=? AND chunk_id=?",
            (self.index_name, chunk_id),
        )
        connection.executemany(
            "INSERT INTO ade_search_lsh(index_name, chunk_id, embedding_provider, table_no, bucket) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (self.index_name, chunk_id, provider, table_no, bucket)
                for table_no, bucket in enumerate(self._lsh_buckets(embedding))
            ],
        )

    def upsert(self, chunk: SearchChunk) -> IndexMutation:
        chunk.validate()
        content_hash = chunk.content_hash
        metadata_json = self._metadata_json(chunk.metadata)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT content_hash, metadata_json, source, embedding_provider, embedding_json "
                "FROM ade_search_chunks WHERE index_name=? AND chunk_id=?",
                (self.index_name, chunk.chunk_id),
            ).fetchone()
            if (
                current
                and current["content_hash"] == content_hash
                and current["metadata_json"] == metadata_json
                and current["source"] == chunk.source
                and current["embedding_provider"] == self.embedder.name
            ):
                lsh_count = connection.execute(
                    "SELECT COUNT(*) FROM ade_search_lsh WHERE index_name=? AND chunk_id=? "
                    "AND embedding_provider=?",
                    (self.index_name, chunk.chunk_id, self.embedder.name),
                ).fetchone()[0]
                if int(lsh_count) != self.lsh_tables:
                    self._write_lsh(
                        connection,
                        chunk.chunk_id,
                        json.loads(current["embedding_json"]),
                        self.embedder.name,
                    )
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
            self._write_lsh(connection, chunk.chunk_id, embedding, self.embedder.name)
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
            connection.execute(
                "DELETE FROM ade_search_lsh WHERE index_name=? AND chunk_id=?",
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
                connection.executemany(
                    "DELETE FROM ade_search_lsh WHERE index_name=? AND chunk_id=?",
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

    def _candidate_rows(
        self,
        query_embedding: Sequence[float],
        lexical_ids: Sequence[str],
    ) -> tuple[list[sqlite3.Row], str, int]:
        with self._connect() as connection:
            row_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM ade_search_chunks WHERE index_name=?",
                    (self.index_name,),
                ).fetchone()[0]
            )
            if row_count <= self.exact_vector_scan_limit:
                rows = connection.execute(
                    "SELECT * FROM ade_search_chunks WHERE index_name=?",
                    (self.index_name,),
                ).fetchall()
                return list(rows), "exact_scan", row_count

            ids: set[str] = set(lexical_ids)
            for table_no, bucket in enumerate(self._lsh_buckets(query_embedding)):
                rows = connection.execute(
                    "SELECT chunk_id FROM ade_search_lsh WHERE index_name=? AND embedding_provider=? "
                    "AND table_no=? AND bucket=? LIMIT ?",
                    (
                        self.index_name,
                        self.embedder.name,
                        table_no,
                        bucket,
                        self.lsh_candidate_limit,
                    ),
                ).fetchall()
                ids.update(str(row["chunk_id"]) for row in rows)
            if not ids:
                return [], "sqlite_lsh_approximate", 0
            ordered = sorted(ids)[: self.lsh_candidate_limit]
            placeholders = ",".join("?" for _ in ordered)
            rows = connection.execute(
                f"SELECT * FROM ade_search_chunks WHERE index_name=? AND chunk_id IN ({placeholders})",
                (self.index_name, *ordered),
            ).fetchall()
            return list(rows), "sqlite_lsh_approximate", len(rows)

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

        lexical: dict[str, tuple[float, int, float]] = {}
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
            lexical[row["chunk_id"]] = (1.0 / rank, rank, raw)

        query_embedding = [float(value) for value in self.embedder.embed(request.query)]
        query_tokens = {token.casefold() for token in _TOKEN.findall(request.query)}
        vector_rows, vector_strategy, vector_candidates = self._candidate_rows(
            query_embedding,
            tuple(lexical.keys()),
        )
        candidates: list[dict[str, Any]] = []
        for row in vector_rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            if not self._matches_filter(metadata, request.filters):
                continue
            embedding = json.loads(row["embedding_json"])
            cosine = self._cosine(query_embedding, embedding)
            vector_score = max(0.0, min(1.0, cosine))
            lexical_score, lexical_rank, lexical_raw = lexical.get(row["chunk_id"], (0.0, 0, 0.0))
            content_tokens = {token.casefold() for token in _TOKEN.findall(row["content"])}
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
                    "lexical_raw": lexical_raw,
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
                "embedding_semantics": (
                    "offline lexical feature projection"
                    if row["embedding_provider"] == DeterministicHashEmbedding.name
                    else "provider supplied"
                ),
                "vector_candidate_strategy": vector_strategy,
                "vector_candidates_scored": vector_candidates,
                "updated_at": row["updated_at"],
            }
            if explain:
                evidence["scoring"] = {
                    "lexical": round(item["lexical_score"], 8),
                    "lexical_rank": item["lexical_rank"] or None,
                    "lexical_bm25_raw": round(item["lexical_raw"], 8),
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
            lsh_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM ade_search_lsh WHERE index_name=? AND embedding_provider=?",
                    (self.index_name, self.embedder.name),
                ).fetchone()[0]
            )
        return {
            "backend": self.backend_name,
            "index_name": self.index_name,
            "chunks": int(row["chunks"]),
            "sources": int(row["sources"]),
            "last_updated": row["last_updated"],
            "embedding_provider": self.embedder.name,
            "database": str(self.database),
            "vector_candidates": {
                "small_index_strategy": "exact_scan",
                "large_index_strategy": "sqlite_lsh_approximate",
                "exact_scan_limit": self.exact_vector_scan_limit,
                "lsh_tables": self.lsh_tables,
                "lsh_bits": self.lsh_bits,
                "lsh_candidate_limit": self.lsh_candidate_limit,
                "persisted_lsh_rows": lsh_rows,
            },
        }