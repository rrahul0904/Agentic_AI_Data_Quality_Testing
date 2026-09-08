from __future__ import annotations
from collections import deque
from .base import ProviderRequest, ProviderResponse

class ScriptedProvider:
    name = "scripted"
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = deque(responses)
        self.requests: list[ProviderRequest] = []
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("scripted provider has no response remaining")
        return self._responses.popleft()
