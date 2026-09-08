from __future__ import annotations

from agentic_data_platform.providers.base import ProviderRequest
from agentic_data_platform.providers.openai_compatible import OpenAICompatibleProvider


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }


class Client:
    def __init__(self):
        self.payload = None

    def post(self, _url, **kwargs):
        self.payload = kwargs["json"]
        return Response()


def test_openai_uses_bounded_completion_and_low_reasoning(monkeypatch):
    monkeypatch.setenv("ADE_OPENAI_REASONING_EFFORT", "low")
    client = Client()
    provider = OpenAICompatibleProvider(
        "openai",
        "https://api.openai.com/v1",
        "test-key",
        client=client,
    )
    provider.generate(
        ProviderRequest(
            model="gpt-5.6-luna",
            messages=[{"role": "user", "content": "Investigate"}],
            max_output_tokens=1600,
        )
    )
    assert client.payload["max_completion_tokens"] == 1600
    assert client.payload["reasoning_effort"] == "low"
    assert "max_tokens" not in client.payload
