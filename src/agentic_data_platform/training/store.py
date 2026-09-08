"""Local project training corpus with deterministic bounded retrieval."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from agentic_data_platform.models import utc_now
from agentic_data_platform.security.redaction import redact_string


_DEFAULT_PATTERNS = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "docs/**/*.md",
    "specs/**/*.md",
    "models/**/*.sql",
    "models/**/*.yml",
    "models/**/*.yaml",
    "dbt_project.yml",
)
_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "logs",
    ".recovery",
}
_SECRET_NAMES = re.compile(
    r"(^|[._-])(env|secret|secrets|credential|credentials|private[_-]?key|token)([._-]|$)",
    re.I,
)


def _safe_relative(root: Path, path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"training file is outside project root: {resolved}") from exc
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        raise ValueError(f"training file is inside an excluded directory: {relative}")
    if _SECRET_NAMES.search(relative.name):
        raise ValueError(f"training refuses likely secret file: {relative}")
    return relative.as_posix()


def _chunks(text: str, *, max_chars: int = 4000, overlap: int = 400) -> list[str]:
    if max_chars <= 0 or overlap < 0 or overlap >= max_chars:
        raise ValueError("invalid chunk bounds")
    normalized = text.replace("\x00", "").strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            newline = normalized.rfind("\n", start + max_chars // 2, end)
            if newline > start:
                end = newline
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return [item for item in chunks if item]


class TrainingStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS training_documents (
              document_id TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              source_type TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              indexed_at TEXT NOT NULL,
              UNIQUE(source, content_hash)
            );
            CREATE TABLE IF NOT EXISTS training_chunks (
              chunk_id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL,
              chunk_index INTEGER NOT NULL,
              content TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              applied_count INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY(document_id) REFERENCES training_documents(document_id)
            );
            CREATE INDEX IF NOT EXISTS idx_training_source ON training_documents(source);
            CREATE INDEX IF NOT EXISTS idx_training_chunk_doc ON training_chunks(document_id, chunk_index);
            """
        )
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(training_chunks)").fetchall()
        }
        if "applied_count" not in columns:
            self.connection.execute(
                "ALTER TABLE training_chunks ADD COLUMN applied_count INTEGER NOT NULL DEFAULT 0"
            )
        try:
            self.connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS training_fts USING fts5(chunk_id UNINDEXED, content)"
            )
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False
        self.connection.commit()

    def ingest_text(
        self,
        source: str,
        text: str,
        *,
        source_type: str = "text",
        metadata: dict[str, Any] | None = None,
        replace_source: bool = True,
    ) -> dict[str, Any]:
        text = redact_string(text)
        raw = text.encode("utf-8")
        content_hash = hashlib.sha256(raw).hexdigest()
        document_id = hashlib.sha256(f"{source}:{content_hash}".encode()).hexdigest()
        existing = self.connection.execute(
            "SELECT document_id FROM training_documents WHERE source = ? AND content_hash = ?",
            (source, content_hash),
        ).fetchone()
        if existing:
            return {
                "status": "UNCHANGED",
                "document_id": existing["document_id"],
                "source": source,
                "chunks": self.connection.execute(
                    "SELECT COUNT(*) AS count FROM training_chunks WHERE document_id = ?",
                    (existing["document_id"],),
                ).fetchone()["count"],
            }
        if replace_source:
            old = self.connection.execute(
                "SELECT document_id FROM training_documents WHERE source = ?",
                (source,),
            ).fetchall()
            for row in old:
                chunk_rows = self.connection.execute(
                    "SELECT chunk_id FROM training_chunks WHERE document_id = ?",
                    (row["document_id"],),
                ).fetchall()
                if self.fts:
                    for chunk in chunk_rows:
                        self.connection.execute(
                            "DELETE FROM training_fts WHERE chunk_id = ?",
                            (chunk["chunk_id"],),
                        )
                self.connection.execute(
                    "DELETE FROM training_chunks WHERE document_id = ?",
                    (row["document_id"],),
                )
                self.connection.execute(
                    "DELETE FROM training_documents WHERE document_id = ?",
                    (row["document_id"],),
                )

        chunks = _chunks(text)
        self.connection.execute(
            "INSERT INTO training_documents VALUES (?, ?, ?, ?, ?, ?)",
            (
                document_id,
                source,
                source_type,
                content_hash,
                json.dumps(metadata or {}, sort_keys=True),
                utc_now(),
            ),
        )
        for index, chunk in enumerate(chunks):
            chunk_hash = hashlib.sha256(chunk.encode()).hexdigest()
            chunk_id = hashlib.sha256(f"{document_id}:{index}:{chunk_hash}".encode()).hexdigest()
            self.connection.execute(
                "INSERT INTO training_chunks(chunk_id, document_id, chunk_index, content, content_hash, applied_count) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (chunk_id, document_id, index, chunk, chunk_hash),
            )
            if self.fts:
                self.connection.execute(
                    "INSERT INTO training_fts(chunk_id, content) VALUES (?, ?)",
                    (chunk_id, chunk),
                )
        self.connection.commit()
        return {
            "status": "INDEXED",
            "document_id": document_id,
            "source": source,
            "chunks": len(chunks),
            "content_hash": content_hash,
        }

    def ingest_file(
        self,
        project_root: str | Path,
        path: str | Path,
        *,
        max_bytes: int = 2_000_000,
    ) -> dict[str, Any]:
        root = Path(project_root).expanduser().resolve()
        source_path = Path(path)
        if not source_path.is_absolute():
            source_path = root / source_path
        source = _safe_relative(root, source_path)
        size = source_path.stat().st_size
        if size > max_bytes:
            return {
                "status": "SKIP",
                "source": source,
                "reason": f"file exceeds max_bytes={max_bytes}",
                "bytes": size,
            }
        raw = source_path.read_bytes()
        if b"\x00" in raw[:4096]:
            return {"status": "SKIP", "source": source, "reason": "binary file"}
        text = raw.decode("utf-8", errors="replace")
        mime, _ = mimetypes.guess_type(source_path.name)
        return self.ingest_text(
            source,
            text,
            source_type="file",
            metadata={"bytes": size, "mime": mime},
        )

    def ingest_project(
        self,
        project_root: str | Path,
        *,
        patterns: Sequence[str] = _DEFAULT_PATTERNS,
        max_files: int = 2000,
        max_bytes_per_file: int = 2_000_000,
    ) -> dict[str, Any]:
        root = Path(project_root).expanduser().resolve()
        candidates: dict[str, Path] = {}
        for pattern in patterns:
            for path in root.glob(pattern):
                if path.is_file():
                    try:
                        relative = _safe_relative(root, path)
                    except ValueError:
                        continue
                    candidates[relative] = path
        if len(candidates) > max_files:
            raise RuntimeError(f"training candidate count {len(candidates)} exceeds max_files={max_files}")
        indexed = unchanged = skipped = 0
        results = []
        for relative, path in sorted(candidates.items()):
            try:
                result = self.ingest_file(root, path, max_bytes=max_bytes_per_file)
            except (OSError, UnicodeError, ValueError) as exc:
                result = {"status": "SKIP", "source": relative, "reason": str(exc)}
            results.append(result)
            if result["status"] == "INDEXED":
                indexed += 1
            elif result["status"] == "UNCHANGED":
                unchanged += 1
            else:
                skipped += 1
        return {
            "status": "PASS",
            "project_root": str(root),
            "indexed": indexed,
            "unchanged": unchanged,
            "skipped": skipped,
            "files": len(results),
            "results": results,
        }

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        if self.fts and query.strip():
            terms = re.findall(r"[A-Za-z0-9_]{2,}", query)
            fts_query = " OR ".join(
                '"' + term.replace('"', '""') + '"'
                for term in terms[:32]
            )
            if not fts_query:
                return []
            rows = self.connection.execute(
                """
                SELECT c.chunk_id, c.chunk_index, c.content, c.applied_count, d.source, d.source_type,
                       d.metadata_json, bm25(training_fts) AS score
                FROM training_fts
                JOIN training_chunks c ON c.chunk_id = training_fts.chunk_id
                JOIN training_documents d ON d.document_id = c.document_id
                WHERE training_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, bounded),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT c.chunk_id, c.chunk_index, c.content, c.applied_count, d.source, d.source_type,
                       d.metadata_json, 0.0 AS score
                FROM training_chunks c
                JOIN training_documents d ON d.document_id = c.document_id
                WHERE lower(c.content) LIKE ?
                ORDER BY d.source, c.chunk_index
                LIMIT ?
                """,
                (f"%{query.casefold()}%", bounded),
            ).fetchall()
        return [
            {
                **dict(row),
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
            for row in rows
        ]

    def context(
        self,
        query: str,
        *,
        limit: int = 8,
        max_chars: int = 12000,
    ) -> dict[str, Any]:
        results = self.search(query, limit=limit)
        selected = []
        used = 0
        for item in results:
            content = str(item["content"])
            remaining = max_chars - used
            if remaining <= 0:
                break
            snippet = content[:remaining]
            selected.append(
                {
                    "chunk_id": item["chunk_id"],
                    "source": item["source"],
                    "chunk_index": item["chunk_index"],
                    "content": snippet,
                    "applied_count_before": int(item.get("applied_count") or 0),
                }
            )
            used += len(snippet)
        if selected:
            chunk_ids = [
                str(item["chunk_id"])
                for item in results[: len(selected)]
            ]
            self.connection.executemany(
                "UPDATE training_chunks SET applied_count = applied_count + 1 WHERE chunk_id = ?",
                [(chunk_id,) for chunk_id in chunk_ids],
            )
            self.connection.commit()
        return {
            "query": query,
            "chunks": selected,
            "characters": used,
            "truncated": len(selected) < len(results) or used >= max_chars,
            "applied_chunk_ids": chunk_ids if selected else [],
        }

    def status(self) -> dict[str, Any]:
        docs = self.connection.execute(
            "SELECT COUNT(*) AS count FROM training_documents"
        ).fetchone()["count"]
        chunks = self.connection.execute(
            "SELECT COUNT(*) AS count FROM training_chunks"
        ).fetchone()["count"]
        latest = self.connection.execute(
            "SELECT MAX(indexed_at) AS latest FROM training_documents"
        ).fetchone()["latest"]
        return {
            "status": "PASS",
            "documents": int(docs),
            "chunks": int(chunks),
            "fts": self.fts,
            "latest_indexed_at": latest,
        }

    def clear(self) -> dict[str, Any]:
        self.connection.execute("DELETE FROM training_chunks")
        self.connection.execute("DELETE FROM training_documents")
        if self.fts:
            self.connection.execute("DELETE FROM training_fts")
        self.connection.commit()
        return {"status": "PASS", "documents": 0, "chunks": 0}
