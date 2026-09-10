"""Safe text extraction for project knowledge documents."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from pypdf import PdfReader


_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".sql",
    ".py",
    ".yml",
    ".yaml",
    ".json",
    ".csv",
}
_SUPPORTED_SUFFIXES = _TEXT_SUFFIXES | {".pdf", ".docx"}


@dataclass(frozen=True)
class DocumentExtraction:
    source: str
    source_type: str
    text: str
    metadata: dict[str, Any]


def _safe_name(filename: str) -> str:
    value = Path(filename or "document").name.strip()
    if not value or value in {".", ".."}:
        raise ValueError("document filename is required")
    return value


def _decode_text(content: bytes) -> str:
    if b"\x00" in content[:4096]:
        raise ValueError("binary content cannot be indexed as plain text")
    return content.decode("utf-8", errors="replace").strip()


def _pdf_text(content: bytes) -> tuple[str, dict[str, Any]]:
    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    extracted_pages = 0
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            extracted_pages += 1
            pages.append(f"[Page {index}]\n{text}")
    return "\n\n".join(pages).strip(), {
        "pages": len(reader.pages),
        "pages_with_text": extracted_pages,
    }


def _docx_text(content: bytes) -> tuple[str, dict[str, Any]]:
    document = Document(io.BytesIO(content))
    blocks: list[str] = []
    paragraph_count = 0
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            paragraph_count += 1
            blocks.append(text)
    table_rows = 0
    for table_index, table in enumerate(document.tables, start=1):
        rows: list[str] = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                table_rows += 1
                rows.append(" | ".join(cells))
        if rows:
            blocks.append(f"[Table {table_index}]\n" + "\n".join(rows))
    return "\n\n".join(blocks).strip(), {
        "paragraphs": paragraph_count,
        "tables": len(document.tables),
        "table_rows": table_rows,
    }


def extract_document(
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
    max_bytes: int = 20_000_000,
) -> DocumentExtraction:
    """Extract bounded textual context from a user-approved document.

    Text PDFs and DOCX are supported. Scanned/image-only PDFs intentionally fail
    closed instead of pretending that OCR succeeded.
    """

    source = _safe_name(filename)
    if not content:
        raise ValueError("document is empty")
    if len(content) > max_bytes:
        raise ValueError(f"document exceeds max_bytes={max_bytes}")

    suffix = Path(source).suffix.casefold()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise ValueError(
            f"unsupported document type {suffix or '<none>'}; "
            f"supported: {', '.join(sorted(_SUPPORTED_SUFFIXES))}"
        )

    metadata: dict[str, Any] = {
        "filename": source,
        "bytes": len(content),
        "content_type": content_type,
        "suffix": suffix,
    }
    if suffix == ".pdf":
        try:
            text, detail = _pdf_text(content)
        except Exception as exc:
            raise ValueError("unable to parse PDF document") from exc
        metadata.update(detail)
        source_type = "pdf"
    elif suffix == ".docx":
        try:
            text, detail = _docx_text(content)
        except Exception as exc:
            raise ValueError("unable to parse DOCX document") from exc
        metadata.update(detail)
        source_type = "docx"
    else:
        text = _decode_text(content)
        source_type = suffix.lstrip(".") or "text"
        if suffix == ".json":
            try:
                text = json.dumps(json.loads(text), indent=2, sort_keys=True)
            except json.JSONDecodeError:
                metadata["parse_warning"] = "invalid_json_indexed_as_text"
        elif suffix == ".csv":
            try:
                rows = list(csv.reader(io.StringIO(text)))
                metadata["rows"] = max(0, len(rows) - 1)
                metadata["columns"] = len(rows[0]) if rows else 0
            except csv.Error:
                metadata["parse_warning"] = "invalid_csv_indexed_as_text"

    if not text.strip():
        if suffix == ".pdf":
            raise ValueError(
                "PDF contains no extractable text; scanned/image-only PDFs require OCR, "
                "which is not enabled in the low-cost local ingestion path"
            )
        raise ValueError("document contains no extractable text")

    metadata["characters"] = len(text)
    return DocumentExtraction(
        source=source,
        source_type=source_type,
        text=text,
        metadata=metadata,
    )
