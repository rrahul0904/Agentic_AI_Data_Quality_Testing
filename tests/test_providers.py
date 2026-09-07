from __future__ import annotations

from agentic_data_platform.providers.anthropic import AnthropicProvider
from agentic_data_platform.providers.base import ProviderRequest
from agentic_data_platform.providers.openai_compatible import OpenAICompatibleProvider
from agentic_data_platform.providers.registry import ProviderRegistry


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.payload)


def request():
    return ProviderRequest(
        model="model",
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}],
        tools=[{"name": "sql_classify", "description": "classify", "input_schema": {"type": "object"}}],
    )


def test_openai_compatible_normalizes_tool_calls_and_usage():
    client = FakeClient({
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "sql_classify", "arguments": '{"sql":"SELECT 1"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    })
    provider = OpenAICompatibleProvider("fixture", "https://example.invalid/v1", "secret", client=client)
    result = provider.generate(request())
    assert result.tool_calls[0].name == "sql_classify"
    assert result.tool_calls[0].args == {"sql": "SELECT 1"}
    assert result.usage.input_tokens == 11
    _, kwargs = client.calls[0]
    assert kwargs["headers"]["authorization"] == "Bearer secret"
    assert kwargs["json"]["tools"][0]["function"]["name"] == "sql_classify"


def test_anthropic_normalizes_text_tool_use_and_cache_usage():
    client = FakeClient({
        "content": [
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "tool-1", "name": "sql_classify", "input": {"sql": "SELECT 1"}},
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 4,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 2,
        },
        "stop_reason": "tool_use",
    })
    provider = AnthropicProvider("secret", base_url="https://example.invalid/v1", client=client)
    result = provider.generate(request())
    assert result.content == "Checking."
    assert result.tool_calls[0].args["sql"] == "SELECT 1"
    assert result.usage.cache_read_tokens == 10
    _, kwargs = client.calls[0]
    assert kwargs["headers"]["x-api-key"] == "secret"
    assert kwargs["json"]["system"] == "system"


def test_provider_registry_exposes_real_protocol_presets(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured")
    registry = ProviderRegistry()
    names = set(registry.names())
    assert {
        "openai", "anthropic", "openrouter", "groq", "mistral", "together", "xai",
        "deepinfra", "nvidia", "cerebras", "perplexity", "vercel",
    }.issubset(names)
    specs = {item["name"]: item for item in registry.specs()}
    assert specs["openrouter"]["configured"] is True
    provider = registry.create("openrouter")
    assert provider.name == "openrouter"
