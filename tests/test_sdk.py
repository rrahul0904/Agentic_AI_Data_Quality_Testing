from agentic_data_platform.sdk import PlatformClient


def test_sdk_uses_only_stable_api_and_injectable_transport():
    calls = []
    def transport(method, url, body, headers):
        calls.append((method, url, body, headers))
        return {"status": "PASS"}
    client = PlatformClient("https://platform.example", token="secret", transport=transport)
    assert client.health()["status"] == "PASS"
    assert calls[0][1] == "https://platform.example/api/v1/platform/health"
    assert calls[0][3]["Authorization"] == "Bearer secret"


def test_sdk_tool_invocation_preserves_governance_fields():
    client = PlatformClient(transport=lambda method, url, body, headers: body)
    result = client.invoke_tool("airflow_backfill_execute", {"dag_id": "hotel"}, actor_mode="builder", approved=True, dry_run=True)
    assert result["actor_mode"] == "builder"
    assert result["approved"] is True
    assert result["dry_run"] is True


def test_sdk_rejects_unstable_paths():
    client = PlatformClient(transport=lambda *args: {})
    try:
        client.get("/internal/anything")
    except ValueError as exc:
        assert "/api/v1" in str(exc)
    else:
        raise AssertionError("unstable path was accepted")
