"""Document-intelligence workflows with deterministic and external provider paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any, Mapping

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.knowledge.documents import DocumentExtraction, extract_document
from agentic_data_platform.providers.base import Provider, ProviderRequest
from agentic_data_platform.security.redaction import redact_string


_STAGE = re.compile(r"^@[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$")
_RESERVED_EVIDENCE_KEY = "_ade_evidence"


@dataclass(frozen=True)
class StructuredDocumentResult:
    status: str
    backend: str
    source: str
    extracted: Mapping[str, Any]
    provenance: Mapping[str, Any]
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def local_document_intelligence(
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
    max_bytes: int = 20_000_000,
) -> dict[str, Any]:
    extraction: DocumentExtraction = extract_document(
        filename,
        content,
        content_type=content_type,
        max_bytes=max_bytes,
    )
    safe_text = redact_string(extraction.text)
    return {
        "status": "PASS",
        "backend": "local_deterministic",
        "source": extraction.source,
        "source_type": extraction.source_type,
        "text": safe_text,
        "metadata": {
            **extraction.metadata,
            "secrets_redacted": safe_text != extraction.text,
        },
    }


def _json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("provider did not return a JSON object")
    value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("provider output must be a JSON object")
    return value


def _confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        normalized = float(value)
        if 0.0 <= normalized <= 1.0:
            return normalized
    return None


def _verified_span(text: str, candidate: str) -> dict[str, Any] | None:
    value = candidate.strip()
    if not value:
        return None
    start = text.find(value)
    if start < 0:
        start = text.casefold().find(value.casefold())
    if start < 0:
        return None
    end = start + len(value)
    context_start = max(0, start - 80)
    context_end = min(len(text), end + 80)
    return {
        "start": start,
        "end": end,
        "quote": text[context_start:context_end],
        "matched_text": text[start:end],
    }


def _literal_candidates(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bool):
        return ["true" if value else "false", "True" if value else "False"]
    if isinstance(value, (str, int, float)):
        return [str(value)]
    return []


def _field_evidence(
    safe_text: str,
    normalized: Mapping[str, Any],
    provider_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    provider_evidence = provider_evidence or {}
    for field, value in normalized.items():
        supplied = provider_evidence.get(field)
        supplied_map = supplied if isinstance(supplied, Mapping) else {}
        supplied_quote = supplied_map.get("quote")
        quote_span = _verified_span(safe_text, str(supplied_quote)) if supplied_quote else None
        literal_span = None
        if quote_span is None:
            for candidate in _literal_candidates(value):
                literal_span = _verified_span(safe_text, candidate)
                if literal_span is not None:
                    break
        confidence = _confidence(supplied_map.get("confidence"))
        source_span = quote_span or literal_span
        result[field] = {
            "value_present": value is not None,
            "source_evidence": (
                "provider_quote_verified"
                if quote_span is not None
                else "exact_literal_verified"
                if literal_span is not None
                else "not_verified_in_source_text"
            ),
            "source_span": source_span,
            "confidence": confidence,
            "confidence_source": "provider_supplied" if confidence is not None else "not_provided",
        }
    return result


def provider_structured_extraction(
    extraction: DocumentExtraction,
    provider: Provider,
    model: str,
    schema: Mapping[str, str],
    *,
    max_output_tokens: int = 2000,
) -> StructuredDocumentResult:
    if not schema:
        raise ValueError("structured extraction schema is required")
    safe_text = redact_string(extraction.text)
    fields = json.dumps(dict(schema), indent=2, sort_keys=True)
    prompt = (
        "Extract the requested fields from the supplied document. "
        "Return JSON only. Do not infer values that are not supported by the document; "
        "use null for missing values. You may optionally include an `_ade_evidence` object "
        "keyed by field, with a short exact source `quote` and a 0..1 `confidence` only when "
        "your backend genuinely provides that confidence. Do not fabricate confidence.\n\n"
        f"Requested fields:\n{fields}\n\nDocument:\n{safe_text}"
    )
    response = provider.generate(
        ProviderRequest(
            model=model,
            messages=[
                {"role": "system", "content": "You are a provenance-preserving document extraction engine."},
                {"role": "user", "content": prompt},
            ],
            max_output_tokens=max(256, min(int(max_output_tokens), 16000)),
            metadata={"source": extraction.source, "task": "document_intelligence"},
        )
    )
    try:
        structured = _json_object(response.content)
    except (ValueError, json.JSONDecodeError) as exc:
        return StructuredDocumentResult(
            status="FAIL",
            backend=getattr(provider, "name", "provider"),
            source=extraction.source,
            extracted={},
            provenance={
                "model": model,
                "usage": asdict(response.usage),
                "finish_reason": response.finish_reason,
                "document_metadata": extraction.metadata,
            },
            error=str(exc),
        )
    requested = set(schema)
    normalized = {key: structured.get(key) for key in schema}
    unexpected = sorted(set(structured) - requested - {_RESERVED_EVIDENCE_KEY})
    raw_evidence = structured.get(_RESERVED_EVIDENCE_KEY)
    provider_evidence = raw_evidence if isinstance(raw_evidence, Mapping) else None
    field_evidence = _field_evidence(safe_text, normalized, provider_evidence)
    return StructuredDocumentResult(
        status="PASS",
        backend=getattr(provider, "name", "provider"),
        source=extraction.source,
        extracted=normalized,
        provenance={
            "model": model,
            "usage": asdict(response.usage),
            "finish_reason": response.finish_reason,
            "unexpected_fields_ignored": unexpected,
            "document_metadata": extraction.metadata,
            "secrets_redacted": safe_text != extraction.text,
            "field_evidence": field_evidence,
            "confidence_semantics": "confidence is null unless explicitly supplied by the provider",
        },
    )


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def snowflake_parse_document_sql(
    stage: str,
    relative_path: str,
    *,
    mode: str = "LAYOUT",
    page_split: bool = True,
    extract_images: bool = False,
    return_error_details: bool = True,
) -> str:
    if not _STAGE.fullmatch(stage.strip()):
        raise ValueError("stage must be an @stage or @db.schema.stage identifier")
    path = relative_path.strip().lstrip("/")
    if not path or ".." in path.split("/"):
        raise ValueError("invalid staged document relative path")
    normalized_mode = mode.upper()
    if normalized_mode not in {"OCR", "LAYOUT"}:
        raise ValueError("mode must be OCR or LAYOUT")
    if extract_images and normalized_mode != "LAYOUT":
        raise ValueError("image extraction requires LAYOUT mode")
    options = {
        "mode": normalized_mode,
        "page_split": bool(page_split),
    }
    if extract_images:
        options["extract_images"] = True
    option_sql = "OBJECT_CONSTRUCT(" + ", ".join(
        f"{_literal(key)}, {('TRUE' if value is True else 'FALSE' if value is False else _literal(str(value)))}"
        for key, value in options.items()
    ) + ")"
    return (
        "SELECT AI_PARSE_DOCUMENT("
        f"TO_FILE({_literal(stage)}, {_literal(path)}), {option_sql}, "
        f"{'TRUE' if return_error_details else 'FALSE'}"
        ") AS parsed_document"
    )


def snowflake_document_intelligence(
    connector: DataPlatformConnector,
    stage: str,
    relative_path: str,
    *,
    mode: str = "LAYOUT",
    page_split: bool = True,
    extract_images: bool = False,
) -> dict[str, Any]:
    if getattr(connector, "platform", "").casefold() != "snowflake":
        raise ValueError("Snowflake document intelligence requires a Snowflake connector")
    sql = snowflake_parse_document_sql(
        stage,
        relative_path,
        mode=mode,
        page_split=page_split,
        extract_images=extract_images,
        return_error_details=True,
    )
    result = connector.execute_read(sql)
    if not result.rows:
        return {
            "status": "FAIL",
            "backend": "snowflake_ai_parse_document",
            "error": "no result returned",
            "sql": sql,
        }
    row = result.rows[0]
    raw = next((value for key, value in row.items() if str(key).casefold() == "parsed_document"), None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {
        "status": "PASS",
        "backend": "snowflake_ai_parse_document",
        "stage": stage,
        "relative_path": relative_path,
        "result": raw,
        "query_id": result.query_id,
        "sql": sql,
    }