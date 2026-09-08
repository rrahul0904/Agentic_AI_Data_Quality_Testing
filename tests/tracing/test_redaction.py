from agentic_data_platform.security.redaction import redact, redact_string
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


def test_common_provider_git_cloud_and_query_secrets_are_redacted():
    samples = [
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123",
        "Authorization: Basic dXNlcjpwYXNzd29yZDEyMzQ1Ng==",
        "github=ghp_abcdefghijklmnopqrstuvwxyz123456",
        "gitlab=glpat-abcdefghijklmnop",
        "aws=AKIAABCDEFGHIJKLMNOP",
        "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature12345",
        "postgresql://alice:database-password@db.example/warehouse",
        "https://example.test/callback?token=query-secret-value&safe=yes",
        "client_secret=provider-secret-value",
    ]
    rendered = "\n".join(redact_string(item) for item in samples)
    for secret in (
        "abcdefghijklmnopqrstuvwxyz123456",
        "abcdefghijklmnop",
        "AKIAABCDEFGHIJKLMNOP",
        "database-password",
        "query-secret-value",
        "provider-secret-value",
        "dXNlcjpwYXNzd29yZDEyMzQ1Ng==",
    ):
        assert secret not in rendered
    assert rendered.count("[REDACTED]") >= len(samples)


def test_generic_token_mapping_key_is_sensitive():
    assert redact({"token": "never-persist-this", "safe": "ok"}) == {
        "token": "[REDACTED]",
        "safe": "ok",
    }


def test_trace_replay_cannot_reconstruct_database_url_or_jwt_from_metadata():
    store = TraceStore()
    event = store.start(
        "tool",
        "connection_test",
        payload={
            "url": "postgresql://alice:database-password@db.example/warehouse",
            "metadata": {
                "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature12345",
                "host": "db.example",
            },
        },
    )
    trace_id = store.show(event)["trace_id"]
    rendered = str(store.replay(trace_id))
    assert "database-password" not in rendered
    assert "signature12345" not in rendered
    assert "db.example" in rendered
