"""Unified project knowledge and document intelligence for ADE OS."""

from .documents import DocumentExtraction, extract_document
from .intelligence import (
    StructuredDocumentResult,
    local_document_intelligence,
    provider_structured_extraction,
    snowflake_document_intelligence,
    snowflake_parse_document_sql,
)
from .pipeline import (
    DocumentAsset,
    DocumentBlock,
    DocumentChunk,
    DocumentIntelligencePipeline,
    OCRProvider,
    ProcessedDocument,
)

__all__ = [
    "DocumentAsset",
    "DocumentBlock",
    "DocumentChunk",
    "DocumentExtraction",
    "DocumentIntelligencePipeline",
    "OCRProvider",
    "ProcessedDocument",
    "StructuredDocumentResult",
    "extract_document",
    "local_document_intelligence",
    "provider_structured_extraction",
    "snowflake_document_intelligence",
    "snowflake_parse_document_sql",
]