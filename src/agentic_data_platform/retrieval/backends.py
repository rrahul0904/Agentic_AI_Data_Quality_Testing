"""Evidence-preserving retrieval backends.

ADE keeps retrieval behind one contract so project-local FTS, Cortex Search and future
providers can be compared without changing the agent/runtime evidence model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, Sequence

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.training import TrainingStore


_SERVICE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$")


@dataclass(frozen=True)
class RetrievalQuery:
    query: str
    limit: int = 10
    columns: tuple[str, ...] = ()
    filters: Mapping[str, Any] | None = None

    def bounded_limit(self) -> int:
        return max(1, min(int(self.limit), 100))

    def validate(self) -> None:
        if not self.query.strip():
            raise ValueError("retrieval query must not be empty")
        if len(self.query) > 20_000:
            raise ValueError("retrieval query exceeds 20,000 characters")
        for column in self.columns:
            if not isinstance(column, str) or not column.strip():
                raise ValueError("retrieval columns must be non-empty strings")


@dataclass(frozen=True)
class RetrievalHit:
    backend: str
    source: str
    content: str
    score: float
    fields: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        body = json.dumps(
            {
                "backend": self.backend,
                "source": self.source,
                "content": self.content,
                "fields": dict(self.fields),
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "source": self.source,
            "content": self.content,
            "score": self.score,
            "fields": dict(self.fields),
            "evidence": dict(self.evidence),
            "fingerprint": self.fingerprint,
        }


class RetrievalBackend(Protocol):
    name: str

    def search(self, request: RetrievalQuery) -> list[RetrievalHit]: ...


class LocalProjectRetrievalBackend:
    name = "local_fts"

    def __init__(self, project_root: str | Path, *, database: str | Path | None = None) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        if database is None:
            database = self.project_root / ".ade" / "training.db"
        self.database = Path(database).expanduser().resolve()

    def search(self, request: RetrievalQuery) -> list[RetrievalHit]:
        request.validate()
        store = TrainingStore(self.database)
        rows = store.search(request.query, limit=request.bounded_limit())
        hits: list[RetrievalHit] = []
        for rank, row in enumerate(rows, 1):
            raw_score = float(row.get("score") or 0.0)
            # SQLite FTS5 bm25 is lower-is-better and is often negative. Keep a stable
            # positive score while retaining the raw value as evidence.
            score = 1.0 / rank if raw_score == 0 else 1.0 / (1.0 + abs(raw_score))
            hits.append(
                RetrievalHit(
                    backend=self.name,
                    source=str(row.get("source") or "project"),
                    content=str(row.get("content") or ""),
                    score=score,
                    fields={
                        "chunk_id": row.get("chunk_id"),
                        "chunk_index": row.get("chunk_index"),
                        "source_type": row.get("source_type"),
                        "metadata": row.get("metadata") or {},
                    },
                    evidence={
                        "rank": rank,
                        "raw_bm25": raw_score,
                        "database": str(self.database),
                    },
                )
            )
        return hits


class CortexSearchBackend:
    """Cortex Search through Snowflake's read-only SEARCH_PREVIEW SQL surface.

    A DataPlatformConnector is injected so the backend inherits ADE connection and
    credential governance. Tests can inject a deterministic fake connector; production
    uses the normal Snowflake connector. The generated call is a SELECT and therefore
    remains inside the connector's read-only boundary.
    """

    name = "snowflake_cortex_search"

    def __init__(
        self,
        connector: DataPlatformConnector,
        service: str,
        *,
        default_columns: Sequence[str] = (),
    ) -> None:
        if getattr(connector, "platform", "").casefold() != "snowflake":
            raise ValueError("CortexSearchBackend requires a Snowflake connector")
        if not _SERVICE.fullmatch(service.strip()):
            raise ValueError("Cortex Search service must be a simple 1-3 part Snowflake identifier")
        self.connector = connector
        self.service = service.strip()
        self.default_columns = tuple(str(item) for item in default_columns if str(item).strip())

    @staticmethod
    def _literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @staticmethod
    def _row_value(row: Mapping[str, Any], key: str) -> Any:
        for name, value in row.items():
            if str(name).casefold() == key.casefold():
                return value
        return None

    def search(self, request: RetrievalQuery) -> list[RetrievalHit]:
        request.validate()
        columns = tuple(request.columns) or self.default_columns
        payload: dict[str, Any] = {
            "query": request.query,
            "limit": request.bounded_limit(),
        }
        if columns:
            payload["columns"] = list(columns)
        if request.filters:
            payload["filter"] = dict(request.filters)
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        sql = (
            "SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW("
            f"{self._literal(self.service)}, {self._literal(payload_json)}"
            "))['results'] AS results"
        )
        result = self.connector.execute_read(sql)
        if not result.rows:
            return []
        raw = self._row_value(result.rows[0], "results")
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, Mapping) and "results" in raw:
            raw = raw["results"]
        if not isinstance(raw, list):
            return []

        hits: list[RetrievalHit] = []
        for rank, item in enumerate(raw[: request.bounded_limit()], 1):
            fields = dict(item) if isinstance(item, Mapping) else {"value": item}
            preferred = None
            for key in ("text", "content", "chunk", "body", "description"):
                value = fields.get(key)
                if isinstance(value, str) and value.strip():
                    preferred = value
                    break
            content = preferred or json.dumps(fields, sort_keys=True, default=str)
            source = str(fields.get("source") or fields.get("path") or fields.get("id") or self.service)
            hits.append(
                RetrievalHit(
                    backend=self.name,
                    source=source,
                    content=content,
                    score=1.0 / rank,
                    fields=fields,
                    evidence={
                        "rank": rank,
                        "service": self.service,
                        "query_id": getattr(result, "query_id", None),
                        "request": payload,
                    },
                )
            )
        return hits


class HybridRetrievalBackend:
    """Fuse ranked results from multiple providers using reciprocal-rank fusion."""

    name = "hybrid"

    def __init__(self, backends: Sequence[RetrievalBackend], *, rrf_k: int = 60) -> None:
        if not backends:
            raise ValueError("at least one retrieval backend is required")
        self.backends = tuple(backends)
        self.rrf_k = max(1, int(rrf_k))

    def search(self, request: RetrievalQuery) -> list[RetrievalHit]:
        request.validate()
        fused: dict[str, dict[str, Any]] = {}
        backend_errors: list[dict[str, str]] = []
        per_backend_limit = max(request.bounded_limit(), min(100, request.bounded_limit() * 2))
        child_request = RetrievalQuery(
            request.query,
            limit=per_backend_limit,
            columns=request.columns,
            filters=request.filters,
        )
        for backend in self.backends:
            try:
                rows = backend.search(child_request)
            except Exception as exc:
                backend_errors.append({"backend": getattr(backend, "name", type(backend).__name__), "error": str(exc)})
                continue
            for rank, hit in enumerate(rows, 1):
                identity = hashlib.sha256(
                    (hit.source.casefold() + "\n" + hit.content.strip()).encode("utf-8")
                ).hexdigest()
                slot = fused.setdefault(
                    identity,
                    {
                        "score": 0.0,
                        "hit": hit,
                        "backends": [],
                        "ranks": {},
                    },
                )
                slot["score"] += 1.0 / (self.rrf_k + rank)
                slot["backends"].append(hit.backend)
                slot["ranks"][hit.backend] = rank
                if hit.score > slot["hit"].score:
                    slot["hit"] = hit

        ordered = sorted(fused.values(), key=lambda item: (-item["score"], item["hit"].source))
        hits = []
        for item in ordered[: request.bounded_limit()]:
            hit: RetrievalHit = item["hit"]
            evidence = dict(hit.evidence)
            evidence.update(
                {
                    "fusion": "reciprocal_rank",
                    "rrf_k": self.rrf_k,
                    "backends": sorted(set(item["backends"])),
                    "ranks": dict(item["ranks"]),
                    "backend_errors": backend_errors,
                }
            )
            hits.append(
                RetrievalHit(
                    backend=self.name,
                    source=hit.source,
                    content=hit.content,
                    score=float(item["score"]),
                    fields=hit.fields,
                    evidence=evidence,
                )
            )
        return hits
