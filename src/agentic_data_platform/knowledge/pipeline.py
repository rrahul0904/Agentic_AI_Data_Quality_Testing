"""Layout-aware, provenance-preserving ADE Document Intelligence pipeline.

The local path is deterministic and deliberately fail-closed for image-only documents when
no OCR provider is supplied. OCR/vision can be injected behind a provider contract without
changing downstream block/chunk/search semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Protocol, Sequence

from agentic_data_platform.retrieval import ADESearchIndex, SearchChunk
from agentic_data_platform.security.redaction import redact_string

from .documents import DocumentExtraction, extract_document


_PAGE_MARKER = re.compile(r"(?m)^\[Page\s+(\d+)\]\s*$")
_TABLE_MARKER = re.compile(r"^\[Table\s+\d+\]$", re.I)
_OCR_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


class OCRProvider(Protocol):
    name: str

    def extract(self, filename: str, content: bytes, *, content_type: str | None = None) -> DocumentExtraction: ...


@dataclass(frozen=True)
class DocumentBlock:
    block_id: str
    kind: str
    text: str
    page: int | None
    confidence: float | None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    text: str
    block_ids: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    content_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProcessedDocument:
    document_id: str
    source: str
    source_type: str
    content_hash: str
    blocks: tuple[DocumentBlock, ...]
    chunks: tuple[DocumentChunk, ...]
    metadata: Mapping[str, Any]
    provenance: Mapping[str, Any]
    index_status: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _document_id(source: str, content_hash: str) -> str:
    return hashlib.sha256(f"{source}\0{content_hash}".encode("utf-8")).hexdigest()


def _split_pages(text: str) -> list[tuple[int | None, str]]:
    matches = list(_PAGE_MARKER.finditer(text))
    if not matches:
        return [(None, text.strip())] if text.strip() else []
    pages: list[tuple[int | None, str]] = []
    prefix = text[: matches[0].start()].strip()
    if prefix:
        pages.append((None, prefix))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            pages.append((int(match.group(1)), body))
    return pages


def _kind(text: str) -> str:
    first = text.splitlines()[0].strip() if text.strip() else ""
    if _TABLE_MARKER.fullmatch(first):
        return "table"
    if first.startswith("#"):
        return "heading"
    if len(first) <= 100 and len(text.splitlines()) == 1 and (
        first.isupper() or (first.istitle() and not first.endswith((".", "?", "!")))
    ):
        return "heading"
    if re.match(r"^(?:[-*•]|\d+[.)])\s+", first):
        return "list"
    return "paragraph"


def _normalized_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if 0.0 <= number <= 1.0:
            return number
    return None


def _blocks(
    document_id: str,
    safe_text: str,
    *,
    parser: str,
    confidence: float | None,
) -> tuple[DocumentBlock, ...]:
    blocks: list[DocumentBlock] = []
    sequence = 0
    for page, page_text in _split_pages(safe_text):
        for raw in re.split(r"\n\s*\n", page_text):
            text = raw.strip()
            if not text:
                continue
            block_id = hashlib.sha256(
                f"{document_id}\0{sequence}\0{page}\0{text}".encode("utf-8")
            ).hexdigest()
            blocks.append(
                DocumentBlock(
                    block_id=block_id,
                    kind=_kind(text),
                    text=text,
                    page=page,
                    confidence=confidence,
                    provenance={
                        "parser": parser,
                        "sequence": sequence,
                        "page": page,
                        "confidence_semantics": (
                            "exact native-parser text"
                            if parser == "native"
                            else "provider supplied when available; otherwise unknown"
                        ),
                    },
                )
            )
            sequence += 1
    return tuple(blocks)


def _chunk_blocks(
    document_id: str,
    blocks: Sequence[DocumentBlock],
    *,
    max_chars: int = 1800,
) -> tuple[DocumentChunk, ...]:
    if max_chars < 256 or max_chars > 100_000:
        raise ValueError("max_chars must be between 256 and 100000")
    groups: list[list[DocumentBlock]] = []
    current: list[DocumentBlock] = []
    current_size = 0
    for block in blocks:
        if len(block.text) > max_chars:
            if current:
                groups.append(current)
                current = []
                current_size = 0
            for offset in range(0, len(block.text), max_chars):
                piece = block.text[offset : offset + max_chars]
                synthetic = DocumentBlock(
                    block_id=f"{block.block_id}:{offset}",
                    kind=block.kind,
                    text=piece,
                    page=block.page,
                    confidence=block.confidence,
                    provenance={**block.provenance, "split_offset": offset},
                )
                groups.append([synthetic])
            continue
        projected = current_size + len(block.text) + (2 if current else 0)
        if current and projected > max_chars:
            groups.append(current)
            current = []
            current_size = 0
        current.append(block)
        current_size += len(block.text) + (2 if current_size else 0)
    if current:
        groups.append(current)

    chunks: list[DocumentChunk] = []
    for index, group in enumerate(groups):
        text = "\n\n".join(block.text for block in group).strip()
        pages = [block.page for block in group if block.page is not None]
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_id = hashlib.sha256(
            f"{document_id}\0{index}\0{content_hash}".encode("utf-8")
        ).hexdigest()
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                text=text,
                block_ids=tuple(block.block_id for block in group),
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                content_hash=content_hash,
                metadata={"chunk_index": index, "block_count": len(group)},
            )
        )
    return tuple(chunks)


class DocumentIntelligencePipeline:
    """Extract, segment, preserve provenance, and optionally sync into ADE Search."""

    def __init__(self, search_index: ADESearchIndex | None = None) -> None:
        self.search_index = search_index

    def _manifest(self, source: str) -> str | None:
        if self.search_index is None:
            return None
        with sqlite3.connect(self.search_index.database) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ade_document_manifest (
                    index_name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    sync_hash TEXT NOT NULL,
                    chunk_ids_json TEXT NOT NULL,
                    PRIMARY KEY(index_name, source)
                )
                """
            )
            row = connection.execute(
                "SELECT sync_hash FROM ade_document_manifest WHERE index_name=? AND source=?",
                (self.search_index.index_name, source),
            ).fetchone()
        return str(row[0]) if row else None

    def _write_manifest(self, source: str, sync_hash: str, chunks: Sequence[DocumentChunk]) -> None:
        if self.search_index is None:
            return
        with sqlite3.connect(self.search_index.database) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ade_document_manifest (
                    index_name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    sync_hash TEXT NOT NULL,
                    chunk_ids_json TEXT NOT NULL,
                    PRIMARY KEY(index_name, source)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO ade_document_manifest(index_name, source, sync_hash, chunk_ids_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(index_name, source) DO UPDATE SET
                    sync_hash=excluded.sync_hash,
                    chunk_ids_json=excluded.chunk_ids_json
                """,
                (
                    self.search_index.index_name,
                    source,
                    sync_hash,
                    json.dumps([chunk.chunk_id for chunk in chunks], separators=(",", ":")),
                ),
            )

    def process(
        self,
        filename: str,
        content: bytes,
        *,
        content_type: str | None = None,
        ocr_provider: OCRProvider | None = None,
        max_bytes: int = 20_000_000,
        max_chunk_chars: int = 1800,
        index_metadata: Mapping[str, Any] | None = None,
    ) -> ProcessedDocument:
        if not content:
            raise ValueError("document is empty")
        if len(content) > max_bytes:
            raise ValueError(f"document exceeds max_bytes={max_bytes}")
        suffix = Path(filename or "document").suffix.casefold()
        content_hash = hashlib.sha256(content).hexdigest()
        parser = "native"
        confidence: float | None = 1.0
        try:
            extraction = extract_document(
                filename,
                content,
                content_type=content_type,
                max_bytes=max_bytes,
            )
        except ValueError:
            if ocr_provider is None or suffix not in _OCR_SUFFIXES:
                raise
            extraction = ocr_provider.extract(filename, content, content_type=content_type)
            parser = f"ocr:{ocr_provider.name}"
            confidence = _normalized_confidence(extraction.metadata.get("confidence"))

        safe_text = redact_string(extraction.text)
        redacted = safe_text != extraction.text
        document_id = _document_id(extraction.source, content_hash)
        blocks = _blocks(document_id, safe_text, parser=parser, confidence=confidence)
        chunks = _chunk_blocks(document_id, blocks, max_chars=max_chunk_chars)
        if not chunks:
            raise ValueError("document produced no indexable chunks")

        index_status: Mapping[str, Any] | None = None
        if self.search_index is not None:
            sync_payload = {
                "content_hash": content_hash,
                "index_metadata": dict(index_metadata or {}),
                "parser": parser,
                "embedding_provider": self.search_index.embedder.name,
                "max_chunk_chars": max_chunk_chars,
            }
            sync_hash = hashlib.sha256(
                json.dumps(sync_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()
            previous_hash = self._manifest(extraction.source)
            if previous_hash == sync_hash:
                index_status = {
                    "status": "NOOP",
                    "reason": "document/index configuration fingerprint unchanged",
                    "sync_hash": sync_hash,
                    "chunks": len(chunks),
                }
            else:
                removed = self.search_index.delete_source(extraction.source)
                search_chunks = [
                    SearchChunk(
                        chunk_id=chunk.chunk_id,
                        source=extraction.source,
                        content=chunk.text,
                        metadata={
                            **dict(index_metadata or {}),
                            "document_id": document_id,
                            "document_hash": content_hash,
                            "source_type": extraction.source_type,
                            "page_start": chunk.page_start,
                            "page_end": chunk.page_end,
                            "block_ids": list(chunk.block_ids),
                            "secrets_redacted": redacted,
                        },
                    )
                    for chunk in chunks
                ]
                mutations = self.search_index.upsert_many(search_chunks)
                self._write_manifest(extraction.source, sync_hash, chunks)
                index_status = {
                    "status": "PASS",
                    "sync_hash": sync_hash,
                    "removed_stale_chunks": removed,
                    "mutations": mutations,
                    "chunks": len(chunks),
                }

        return ProcessedDocument(
            document_id=document_id,
            source=extraction.source,
            source_type=extraction.source_type,
            content_hash=content_hash,
            blocks=blocks,
            chunks=chunks,
            metadata={**extraction.metadata, "secrets_redacted": redacted},
            provenance={
                "parser": parser,
                "source": extraction.source,
                "content_hash": content_hash,
                "document_id": document_id,
                "redaction_applied": redacted,
                "ocr_used": parser.startswith("ocr:"),
                "confidence": confidence,
            },
            index_status=index_status,
        )
