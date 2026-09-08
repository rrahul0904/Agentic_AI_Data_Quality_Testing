from agentic_data_platform.security.redaction import redact
from agentic_data_platform.tracing.store import TraceStore


def test_secret_redaction_is_recursive():
    value = redact({"password": "super-secret-password", "nested": {"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz"}, "text": "api_key=abcdefghijklmnop"})
    assert value["password"] == "[REDACTED]"
    assert value["nested"]["Authorization"] == "[REDACTED]"
    assert "abcdefghijklmnop" not in value["text"]


def test_trace_store_never_replays_raw_secret():
    store = TraceStore()
    event = store.start("tool", "connection_test", payload={"args": {"password": "never-store-this"}})
    trace_id = store.show(event)["trace_id"]
    store.finish(event, "SUCCESS", {"result": {"access_token": "also-secret"}})
    rendered = str(store.replay(trace_id))
    assert "never-store-this" not in rendered
    assert "also-secret" not in rendered
    assert "[REDACTED]" in rendered
