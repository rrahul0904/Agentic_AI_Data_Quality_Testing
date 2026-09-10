"""Multi-index ADE Search orchestration and reranking contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Protocol, Sequence

from .backends import RetrievalHit, RetrievalQuery
from .index import ADESearchIndex
from .scoring import ScoringProfile


class Reranker(Protocol):
    name: str

    def score(self, query: str, hit: RetrievalHit) -> float: ...


class TokenOverlapReranker:
    """Deterministic local reranker; intentionally not described as semantic ML."""

    name = "token_overlap_v1"

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token.casefold() for token in text.replace("_", " ").split() if token.strip()}

    def score(self, query: str, hit: RetrievalHit) -> float:
        query_tokens = self._tokens(query)
        if not query_tokens:
            return 0.0
        hit_tokens = self._tokens(hit.content)
        return len(query_tokens & hit_tokens) / len(query_tokens)


@dataclass(frozen=True)
class MultiIndexSearchResult:
    query: str
    index_names: tuple[str, ...]
    hits: tuple[RetrievalHit, ...]
    reranker: str

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "index_names": list(self.index_names),
            "reranker": self.reranker,
            "results": [hit.as_dict() for hit in self.hits],
        }


class ADESearchEngine:
    """Fuse candidates from multiple ADE Search indexes, rerank, then apply metadata scoring."""

    def __init__(
        self,
        indexes: Mapping[str, ADESearchIndex],
        *,
        reranker: Reranker | None = None,
        rrf_k: int = 60,
    ) -> None:
        if not indexes:
            raise ValueError("at least one search index is required")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        self.indexes = dict(indexes)
        self.reranker = reranker or TokenOverlapReranker()
        self.rrf_k = int(rrf_k)

    def search(
        self,
        request: RetrievalQuery,
        *,
        index_names: Sequence[str] | None = None,
        scoring_profile: ScoringProfile | None = None,
        fusion_weight: float = 0.7,
        rerank_weight: float = 0.2,
        metadata_weight: float = 0.1,
    ) -> MultiIndexSearchResult:
        request.validate()
        names = tuple(index_names or self.indexes.keys())
        if not names:
            raise ValueError("at least one index_name is required")
        missing = [name for name in names if name not in self.indexes]
        if missing:
            raise KeyError(f"unknown search indexes: {', '.join(sorted(missing))}")
        weights = [float(fusion_weight), float(rerank_weight), float(metadata_weight)]
        if scoring_profile is None:
            weights[2] = 0.0
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("search-stage weights must be non-negative with positive sum")
        weight_total = sum(weights)
        fusion_weight, rerank_weight, metadata_weight = (
            weight / weight_total for weight in weights
        )

        per_index_limit = max(request.bounded_limit() * 4, 20)
        child_request = RetrievalQuery(
            request.query,
            limit=min(100, per_index_limit),
            columns=request.columns,
            filters=request.filters,
        )
        fused: dict[str, dict[str, object]] = {}
        errors: list[dict[str, str]] = []
        for name in names:
            index = self.indexes[name]
            try:
                candidates = index.search(
                    child_request,
                    lexical_weight=0.5,
                    vector_weight=0.5,
                    rerank_weight=0.0,
                    explain=True,
                )
            except Exception as exc:
                errors.append({"index": name, "error": str(exc)})
                continue
            for rank, hit in enumerate(candidates, 1):
                identity = hashlib.sha256(
                    f"{hit.source.casefold()}\0{hit.content.strip()}".encode("utf-8")
                ).hexdigest()
                slot = fused.setdefault(
                    identity,
                    {
                        "hit": hit,
                        "rrf": 0.0,
                        "indexes": [],
                        "ranks": {},
                    },
                )
                slot["rrf"] = float(slot["rrf"]) + 1.0 / (self.rrf_k + rank)
                slot["indexes"].append(name)  # type: ignore[union-attr]
                slot["ranks"][name] = rank  # type: ignore[index]
                if hit.score > slot["hit"].score:  # type: ignore[union-attr]
                    slot["hit"] = hit

        if not fused:
            return MultiIndexSearchResult(request.query, names, (), self.reranker.name)

        max_rrf = max(float(slot["rrf"]) for slot in fused.values()) or 1.0
        scored: list[tuple[float, RetrievalHit]] = []
        for slot in fused.values():
            hit: RetrievalHit = slot["hit"]  # type: ignore[assignment]
            fusion_score = float(slot["rrf"]) / max_rrf
            reranker_score = max(0.0, min(1.0, float(self.reranker.score(request.query, hit))))
            metadata = hit.fields.get("metadata", {}) if isinstance(hit.fields, Mapping) else {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            profile_score = 0.0
            profile_evidence: dict[str, object] = {}
            if scoring_profile is not None:
                profile_score, profile_evidence = scoring_profile.score(metadata)
            final_score = (
                fusion_weight * fusion_score
                + rerank_weight * reranker_score
                + metadata_weight * profile_score
            )
            evidence = dict(hit.evidence)
            evidence["multi_index"] = {
                "fusion": "reciprocal_rank",
                "rrf_k": self.rrf_k,
                "fusion_score": fusion_score,
                "indexes": sorted(set(slot["indexes"])),
                "ranks": dict(slot["ranks"]),
                "index_errors": errors,
                "reranker": self.reranker.name,
                "reranker_score": reranker_score,
                "metadata_profile": profile_evidence,
                "weights": {
                    "fusion": fusion_weight,
                    "rerank": rerank_weight,
                    "metadata": metadata_weight,
                },
                "final": final_score,
            }
            scored.append(
                (
                    final_score,
                    RetrievalHit(
                        backend="ade_search_multi_index",
                        source=hit.source,
                        content=hit.content,
                        score=final_score,
                        fields=hit.fields,
                        evidence=evidence,
                    ),
                )
            )
        scored.sort(key=lambda item: (-item[0], item[1].source, item[1].fingerprint))
        return MultiIndexSearchResult(
            query=request.query,
            index_names=names,
            hits=tuple(hit for _, hit in scored[: request.bounded_limit()]),
            reranker=self.reranker.name,
        )
