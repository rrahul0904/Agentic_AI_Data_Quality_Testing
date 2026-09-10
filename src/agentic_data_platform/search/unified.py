"""Cross-system hybrid semantic search for ADE project and warehouse context."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable, Sequence


_WORD = re.compile(r"[A-Za-z0-9_$]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DEFAULT_EXTENSIONS = frozenset({
    ".sql", ".py", ".yml", ".yaml", ".md", ".txt", ".json", ".toml",
    ".tsx", ".ts", ".jsx", ".js", ".java", ".scala", ".sh",
})
_IGNORE_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "target", "dist", "build",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})
_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("billing", "payment", "amount", "revpar", "adr", "sales", "folio"),
    "reservation": ("booking", "stay", "guest", "room"),
    "freshness": ("latency", "stale", "late", "watermark", "updated"),
    "connection": ("credential", "auth", "database", "warehouse", "connector"),
    "lineage": ("dependency", "upstream", "downstream", "graph", "depends"),
    "quality": ("validation", "test", "anomaly", "reconcile", "assertion"),
    "snowpipe": ("pipe", "copy", "stage", "ingest", "load"),
    "stream": ("cdc", "change", "delta", "backlog"),
    "airflow": ("dag", "task", "scheduler", "orchestration"),
    "dbt": ("model", "manifest", "compile", "build", "snapshot"),
    "semantic": ("metric", "dimension", "measure", "business"),
}
EmbeddingFn = Callable[[str], Sequence[float]]


@dataclass(frozen=True)
class SearchDocument:
    document_id: str
    kind: str
    source: str
    title: str
    content: str
    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    metadata: dict[str, Any] | None = None


def _tokens(text: str) -> list[str]:
    expanded = _CAMEL.sub(" ", str(text or "")).replace("_", " ").replace("-", " ")
    return [item.casefold() for item in _WORD.findall(expanded) if len(item) > 1]


def _expanded_tokens(text: str) -> list[str]:
    tokens = _tokens(text)
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(_CONCEPTS.get(token, ()))
        for concept, synonyms in _CONCEPTS.items():
            if token in synonyms:
                expanded.append(concept)
    return list(dict.fromkeys(expanded))


def _local_features(text: str, dimensions: int = 768) -> dict[int, float]:
    tokens = _expanded_tokens(text)
    counts: Counter[int] = Counter()
    for token in tokens:
        features = [f"w:{token}"]
        padded = f"^{token}$"
        features.extend(f"c3:{padded[i:i+3]}" for i in range(max(1, len(padded) - 2)))
        for feature in features:
            slot = int(sha256(feature.encode("utf-8")).hexdigest()[:8], 16) % dimensions
            counts[slot] += 1
    norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {key: value / norm for key, value in counts.items()}


def _cosine_sparse(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def _cosine_dense(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    ln = math.sqrt(sum(float(a) * float(a) for a in left))
    rn = math.sqrt(sum(float(b) * float(b) for b in right))
    return dot / (ln * rn) if ln and rn else 0.0


def _kind_for(path: Path) -> str:
    parts = {item.casefold() for item in path.parts}
    name = path.name.casefold()
    if "models" in parts and path.suffix.casefold() in {".sql", ".yml", ".yaml"}:
        return "dbt"
    if "dags" in parts or "airflow" in parts:
        return "airflow"
    if path.suffix.casefold() == ".sql":
        return "sql"
    if path.suffix.casefold() in {".md", ".txt"} or "docs" in parts:
        return "documentation"
    if path.suffix.casefold() in {".yml", ".yaml", ".json", ".toml"}:
        return "configuration"
    if name in {"readme", "readme.md", "agents.md", "claude.md"}:
        return "documentation"
    return "code"


def _chunks(text: str, *, max_chars: int = 5000, overlap_lines: int = 4) -> Iterable[tuple[int, int, str]]:
    lines = text.splitlines()
    start = 0
    while start < len(lines):
        used = 0
        end = start
        while end < len(lines):
            size = len(lines[end]) + 1
            if end > start and used + size > max_chars:
                break
            used += size
            end += 1
        if end == start:
            end += 1
        yield start + 1, end, "\n".join(lines[start:end])
        if end >= len(lines):
            break
        start = max(start + 1, end - overlap_lines)


class UnifiedSemanticIndex:
    """Local-first hybrid index spanning code, docs, dbt, Airflow and warehouse metadata.

    External embeddings are optional. Without them, ADE uses a deterministic
    concept-expanded hashed feature index, so search remains private/offline.
    """

    def __init__(self, path: str | Path = ":memory:", *, embedding_fn: EmbeddingFn | None = None) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.embedding_fn = embedding_fn
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS search_documents (
              document_id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              source TEXT NOT NULL,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              path TEXT,
              line_start INTEGER,
              line_end INTEGER,
              metadata_json TEXT NOT NULL,
              local_features_json TEXT NOT NULL,
              embedding_json TEXT
            )
        """)
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_search_kind ON search_documents(kind)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_search_source ON search_documents(source)")
        try:
            self.connection.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts USING fts5(
                  document_id UNINDEXED,
                  title,
                  content,
                  tokenize='porter unicode61'
                )
            """)
            self._fts = True
        except sqlite3.OperationalError:
            self._fts = False
        self.connection.commit()

    def upsert(self, document: SearchDocument) -> None:
        local = _local_features(f"{document.title}\n{document.content}")
        embedding = (
            [float(value) for value in self.embedding_fn(f"{document.title}\n{document.content}")]
            if self.embedding_fn is not None
            else None
        )
        self.connection.execute(
            """
            INSERT INTO search_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
              kind=excluded.kind,
              source=excluded.source,
              title=excluded.title,
              content=excluded.content,
              path=excluded.path,
              line_start=excluded.line_start,
              line_end=excluded.line_end,
              metadata_json=excluded.metadata_json,
              local_features_json=excluded.local_features_json,
              embedding_json=excluded.embedding_json
            """,
            (
                document.document_id,
                document.kind,
                document.source,
                document.title,
                document.content,
                document.path,
                document.line_start,
                document.line_end,
                json.dumps(document.metadata or {}, sort_keys=True, default=str),
                json.dumps(local, sort_keys=True),
                json.dumps(embedding) if embedding is not None else None,
            ),
        )
        if self._fts:
            self.connection.execute("DELETE FROM search_documents_fts WHERE document_id = ?", (document.document_id,))
            self.connection.execute(
                "INSERT INTO search_documents_fts(document_id, title, content) VALUES (?, ?, ?)",
                (document.document_id, document.title, document.content),
            )
        self.connection.commit()

    def index_project(
        self,
        root: str | Path,
        *,
        extensions: Iterable[str] = _DEFAULT_EXTENSIONS,
        max_file_bytes: int = 1_000_000,
        max_files: int = 10_000,
    ) -> dict[str, Any]:
        root_path = Path(root).expanduser().resolve()
        allowed = {str(item).casefold() for item in extensions}
        indexed = skipped = 0
        for path in root_path.rglob("*"):
            if indexed >= max_files:
                break
            if not path.is_file() or any(part.casefold() in _IGNORE_DIRS for part in path.relative_to(root_path).parts[:-1]):
                continue
            if path.suffix.casefold() not in allowed and path.name.casefold() not in {"readme", "agents.md", "claude.md"}:
                continue
            try:
                if path.stat().st_size > max_file_bytes:
                    skipped += 1
                    continue
                text = path.read_text(errors="replace")
            except OSError:
                skipped += 1
                continue
            relative = path.relative_to(root_path).as_posix()
            digest = sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
            for chunk_index, (line_start, line_end, content) in enumerate(_chunks(text)):
                doc_id = f"project:{relative}:{digest}:{chunk_index}"
                self.upsert(SearchDocument(
                    document_id=doc_id,
                    kind=_kind_for(path),
                    source="project",
                    title=relative,
                    content=content,
                    path=relative,
                    line_start=line_start,
                    line_end=line_end,
                    metadata={"sha256": digest, "chunk_index": chunk_index},
                ))
            indexed += 1
        return {
            "status": "PASS",
            "root": str(root_path),
            "files_indexed": indexed,
            "files_skipped": skipped,
            "document_count": self.count(),
            "embedding_backend": "external" if self.embedding_fn else "local_private",
        }

    def index_metadata(self, service: Any, *, connection_name: str | None = None, limit: int = 5000) -> dict[str, Any]:
        assets = service.search_assets("", connection_name=connection_name, limit=limit)
        indexed = 0
        for asset in assets:
            try:
                detail = service.inspect(asset["connection_name"], asset["schema_name"], asset["object_name"])
            except (KeyError, ValueError):
                detail = dict(asset)
                detail["columns"] = []
            qualified = ".".join(
                str(value) for value in (
                    detail.get("catalog"),
                    detail.get("schema_name"),
                    detail.get("object_name"),
                ) if value
            )
            columns = detail.get("columns", [])
            content = "\n".join([
                f"warehouse={detail.get('warehouse')}",
                f"connection={detail.get('connection_name')}",
                f"type={detail.get('object_type')}",
                f"comment={detail.get('comment') or ''}",
                "columns=" + ", ".join(
                    f"{column.get('column_name')} {column.get('data_type') or ''}"
                    for column in columns
                ),
            ])
            self.upsert(SearchDocument(
                document_id=f"metadata:{detail.get('object_id')}",
                kind="warehouse_object",
                source=str(detail.get("connection_name") or "warehouse"),
                title=qualified or str(detail.get("object_name")),
                content=content,
                metadata={
                    "warehouse": detail.get("warehouse"),
                    "catalog": detail.get("catalog"),
                    "schema": detail.get("schema_name"),
                    "object": detail.get("object_name"),
                    "object_type": detail.get("object_type"),
                    "columns": [column.get("column_name") for column in columns],
                },
            ))
            indexed += 1
        return {
            "status": "PASS",
            "objects_indexed": indexed,
            "document_count": self.count(),
            "embedding_backend": "external" if self.embedding_fn else "local_private",
        }

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM search_documents").fetchone()[0])

    def _keyword_candidates(self, query: str, limit: int) -> list[tuple[str, float]]:
        terms = _expanded_tokens(query)
        if not terms:
            return []
        if self._fts:
            expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms[:32])
            try:
                rows = self.connection.execute(
                    """
                    SELECT document_id, bm25(search_documents_fts, 3.0, 1.0) AS score
                    FROM search_documents_fts
                    WHERE search_documents_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (expression, limit),
                ).fetchall()
                return [(str(row["document_id"]), 1.0 / (1.0 + max(0.0, float(row["score"])))) for row in rows]
            except sqlite3.OperationalError:
                pass
        clauses = " OR ".join("lower(title || ' ' || content) LIKE ?" for _ in terms[:16])
        params = [f"%{term}%" for term in terms[:16]]
        rows = self.connection.execute(
            f"SELECT document_id FROM search_documents WHERE {clauses} LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [(str(row["document_id"]), 0.5) for row in rows]

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        kinds: Iterable[str] = (),
        limit: int = 20,
        candidate_limit: int = 2000,
    ) -> dict[str, Any]:
        mode = str(mode).casefold()
        if mode not in {"keyword", "semantic", "hybrid"}:
            raise ValueError("search mode must be keyword, semantic, or hybrid")
        limit = max(1, min(int(limit), 100))
        candidate_limit = max(limit, min(int(candidate_limit), 20_000))
        allowed_kinds = {str(item) for item in kinds}

        keyword = self._keyword_candidates(query, max(limit * 10, 100)) if mode in {"keyword", "hybrid"} else []
        keyword_scores = {doc_id: score for doc_id, score in keyword}

        rows = self.connection.execute(
            "SELECT * FROM search_documents LIMIT ?",
            (candidate_limit,),
        ).fetchall()
        query_local = _local_features(query)
        query_embedding = (
            [float(value) for value in self.embedding_fn(query)]
            if self.embedding_fn is not None and mode in {"semantic", "hybrid"}
            else None
        )

        ranked: list[tuple[float, sqlite3.Row, dict[str, Any]]] = []
        for row in rows:
            if allowed_kinds and str(row["kind"]) not in allowed_kinds:
                continue
            keyword_score = keyword_scores.get(str(row["document_id"]), 0.0)
            local_features = {int(key): float(value) for key, value in json.loads(row["local_features_json"]).items()}
            local_score = _cosine_sparse(query_local, local_features)
            external_score = 0.0
            if query_embedding is not None and row["embedding_json"]:
                external_score = max(0.0, _cosine_dense(query_embedding, json.loads(row["embedding_json"])))
            if mode == "keyword":
                score = keyword_score
            elif mode == "semantic":
                score = 0.75 * external_score + 0.25 * local_score if query_embedding is not None else local_score
            else:
                semantic_score = 0.75 * external_score + 0.25 * local_score if query_embedding is not None else local_score
                score = 0.45 * keyword_score + 0.55 * semantic_score
                if keyword_score and semantic_score:
                    score += 0.10
            if score <= 0:
                continue
            ranked.append((score, row, {
                "keyword": round(keyword_score, 6),
                "local_semantic": round(local_score, 6),
                "external_embedding": round(external_score, 6),
            }))

        ranked.sort(key=lambda item: (-item[0], str(item[1]["kind"]), str(item[1]["title"])))
        results = []
        for score, row, components in ranked[:limit]:
            content = str(row["content"])
            results.append({
                "document_id": row["document_id"],
                "kind": row["kind"],
                "source": row["source"],
                "title": row["title"],
                "path": row["path"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "score": round(float(score), 6),
                "score_components": components,
                "snippet": content[:1200],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            })
        return {
            "status": "PASS",
            "query": query,
            "mode": mode,
            "result_count": len(results),
            "embedding_backend": "external" if query_embedding is not None else "local_private",
            "results": results,
        }
