"""Portable HTTP embedding and reranking providers for ADE Search."""

from __future__ import annotations

import math
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import httpx

from .backends import RetrievalHit


class HTTPClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> Any: ...


def _validate_endpoint(endpoint: str, *, allow_insecure_http: bool) -> str:
    value = endpoint.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("provider endpoint must be an absolute http(s) URL")
    if parsed.scheme == "http" and not allow_insecure_http:
        host = (parsed.hostname or "").casefold()
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("plain HTTP provider endpoints require allow_insecure_http=True")
    return value


def _headers(api_key: str | None, headers: Mapping[str, str] | None) -> dict[str, str]:
    result = {str(key): str(value) for key, value in dict(headers or {}).items()}
    if api_key:
        result.setdefault("Authorization", f"Bearer {api_key}")
    result.setdefault("Content-Type", "application/json")
    return result


class HTTPEmbeddingProvider:
    """Embedding adapter for the common JSON ``model`` + ``input`` contract.

    Expected response shape is ``{"data": [{"embedding": [...]}]}``. This keeps ADE
    independent of a specific model vendor while supporting self-hosted or managed services.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 30.0,
        allow_insecure_http: bool = False,
        client: HTTPClient | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("embedding model is required")
        self.endpoint = _validate_endpoint(endpoint, allow_insecure_http=allow_insecure_http)
        self.model = model.strip()
        self.name = f"http_embedding:{self.model}"
        self._headers = _headers(api_key, headers)
        self._timeout = max(1.0, min(float(timeout_seconds), 300.0))
        self._client = client

    def embed(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("embedding input must not be empty")
        client = self._client or httpx.Client(timeout=self._timeout)
        close = self._client is None
        try:
            response = client.post(
                self.endpoint,
                headers=self._headers,
                json={"model": self.model, "input": text},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if close and hasattr(client, "close"):
                client.close()
        try:
            vector = [float(value) for value in payload["data"][0]["embedding"]]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError("embedding provider returned an invalid response") from exc
        if not vector or len(vector) > 65_536 or any(not math.isfinite(value) for value in vector):
            raise ValueError("embedding vector must contain bounded finite numeric values")
        return vector


class HTTPReranker:
    """Portable single-document reranker using a JSON query/documents contract."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 30.0,
        allow_insecure_http: bool = False,
        client: HTTPClient | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("reranker model is required")
        self.endpoint = _validate_endpoint(endpoint, allow_insecure_http=allow_insecure_http)
        self.model = model.strip()
        self.name = f"http_reranker:{self.model}"
        self._headers = _headers(api_key, headers)
        self._timeout = max(1.0, min(float(timeout_seconds), 300.0))
        self._client = client

    def score(self, query: str, hit: RetrievalHit) -> float:
        client = self._client or httpx.Client(timeout=self._timeout)
        close = self._client is None
        try:
            response = client.post(
                self.endpoint,
                headers=self._headers,
                json={"model": self.model, "query": query, "documents": [hit.content]},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if close and hasattr(client, "close"):
                client.close()
        value = None
        if isinstance(payload, Mapping):
            scores = payload.get("scores")
            if isinstance(scores, list) and scores:
                value = scores[0]
            results = payload.get("results")
            if value is None and isinstance(results, list) and results and isinstance(results[0], Mapping):
                value = results[0].get("score", results[0].get("relevance_score"))
        try:
            score = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("reranker provider returned no numeric score") from exc
        if not math.isfinite(score):
            raise ValueError("reranker score must be finite")
        return max(0.0, min(1.0, score))
