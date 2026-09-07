from __future__ import annotations

from agentic_data_platform.providers import (
    AzureOpenAIProvider,
    BedrockProvider,
    GeminiProvider,
    ProviderRegistry,
    ProviderRequest,
    VertexAIProvider,
)


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.payload)


def request():
    return ProviderRequest(
        model="fixture-model",
        messages=[
            {"role": "system", "content": "Use deterministic evidence."},
            {"role": "user", "content": "classify SQL"},
        ],
        tools=[
            {
                "name": "sql_classify",
                "description": "classify sql",
                "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}},
            }
        ],
        max_output_tokens=512,
    )


def test_gemini_normalizes_text_tool_calls_and_usage():
    client = FakeHttpClient({
        "candidates": [{
            "content": {
                "parts": [
                    {"text": "Checking."},
                    {"functionCall": {"name": "sql_classify", "args": {"sql": "SELECT 1"}, "id": "g1"}},
                ]
            },
            "finishReason": "STOP",
        }],
        "usageMetadata": {
            "promptTokenCount": 11,
            "candidatesTokenCount": 4,
            "thoughtsTokenCount": 2,
            "cachedContentTokenCount": 1,
        },
    })
    provider = GeminiProvider("secret", base_url="https://example.invalid/v1beta", client=client)
    result = provider.generate(request())
    assert result.content == "Checking."
    assert result.tool_calls[0].name == "sql_classify"
    assert result.tool_calls[0].args == {"sql": "SELECT 1"}
    assert result.usage.input_tokens == 11
    assert result.usage.reasoning_tokens == 2
    _, kwargs = client.calls[0]
    assert kwargs["params"]["key"] == "secret"
    assert kwargs["json"]["tools"][0]["functionDeclarations"][0]["name"] == "sql_classify"


def test_vertex_uses_bearer_auth_and_gemini_contract():
    client = FakeHttpClient({
        "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
    })
    provider = VertexAIProvider("project-1", "us-central1", "token", client=client)
    result = provider.generate(request())
    assert result.content == "ok"
    url, kwargs = client.calls[0]
    assert "projects/project-1/locations/us-central1" in url
    assert kwargs["headers"]["authorization"] == "Bearer token"


def test_azure_openai_normalizes_tool_calls_and_usage():
    client = FakeHttpClient({
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "function": {"name": "sql_classify", "arguments": '{"sql":"SELECT 1"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 3,
            "completion_tokens_details": {"reasoning_tokens": 1},
        },
    })
    provider = AzureOpenAIProvider(
        "https://example.openai.azure.com",
        "secret",
        "deployment-a",
        client=client,
    )
    result = provider.generate(request())
    assert result.tool_calls[0].args["sql"] == "SELECT 1"
    assert result.usage.reasoning_tokens == 1
    url, kwargs = client.calls[0]
    assert "/openai/deployments/deployment-a/chat/completions" in url
    assert kwargs["headers"]["api-key"] == "secret"
    assert kwargs["params"]["api-version"]


class FakeBedrockClient:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "output": {
                "message": {
                    "content": [
                        {"text": "Checking."},
                        {
                            "toolUse": {
                                "toolUseId": "tool-1",
                                "name": "sql_classify",
                                "input": {"sql": "SELECT 1"},
                            }
                        },
                    ]
                }
            },
            "usage": {"inputTokens": 7, "outputTokens": 2},
            "stopReason": "tool_use",
        }


def test_bedrock_converse_normalizes_tools_and_usage():
    client = FakeBedrockClient()
    provider = BedrockProvider(region="us-east-1", client=client)
    result = provider.generate(request())
    assert result.content == "Checking."
    assert result.tool_calls[0].name == "sql_classify"
    assert result.usage.input_tokens == 7
    call = client.calls[0]
    assert call["modelId"] == "fixture-model"
    assert call["toolConfig"]["tools"][0]["toolSpec"]["name"] == "sql_classify"


def test_provider_registry_includes_expanded_first_class_adapters(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "configured")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "configured")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "deployment")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GOOGLE_CLOUD_ACCESS_TOKEN", "token")

    registry = ProviderRegistry()
    names = set(registry.names())
    assert {"gemini", "vertex", "azure-openai", "bedrock", "ollama"}.issubset(names)
    specs = {item["name"]: item for item in registry.specs()}
    assert specs["gemini"]["configured"] is True
    assert specs["azure-openai"]["configured"] is True
    assert specs["vertex"]["configured"] is True
    assert specs["ollama"]["protocol"] == "openai-compatible"
