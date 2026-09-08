from __future__ import annotations

from agentic_data_platform.review.e2e import (
    discover_github_pull,
    discover_gitlab_merge_request,
    sync_github_review_comment,
    sync_gitlab_review_note,
)


REVIEW = {
    "verdict": "COMMENT",
    "signature": "abc123",
    "blockers": [],
    "comments": [{"type": "impact", "model": "fct_orders"}],
    "evidence": {"changed_models": [], "validators": {"blocking": []}, "failed_tests": [], "sql_findings": []},
}


def test_github_discovers_pull_and_changed_files(monkeypatch):
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "not-a-real-token")
    calls = []

    def transport(method, url, headers, payload):
        calls.append((method, url, payload))
        if url.endswith("/files?per_page=100"):
            return {"http_status": 200, "body": [{"filename": "models/fct_orders.sql"}, {"filename": "models/schema.yml"}]}
        return {"http_status": 200, "body": {"title": "dbt change", "state": "open", "base": {"sha": "base"}, "head": {"sha": "head"}}}

    result = discover_github_pull("acme/analytics", 12, token_env="TEST_GITHUB_TOKEN", transport=transport)
    assert result["status"] == "PASS"
    assert result["changed_files"] == ["models/fct_orders.sql", "models/schema.yml"]
    assert calls[0][1].endswith("/repos/acme/analytics/pulls/12")


def test_gitlab_supports_self_hosted_api_and_changes(monkeypatch):
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "not-a-real-token")
    urls = []

    def transport(method, url, headers, payload):
        urls.append(url)
        if url.endswith("/changes"):
            return {"http_status": 200, "body": {"changes": [{"new_path": "models/fct_orders.sql"}]}}
        return {"http_status": 200, "body": {"title": "MR", "state": "opened", "diff_refs": {"base_sha": "b", "head_sha": "h"}}}

    result = discover_gitlab_merge_request("team/analytics", 7, token_env="TEST_GITLAB_TOKEN", api_url="https://gitlab.internal.example/api/v4", transport=transport)
    assert result["status"] == "PASS"
    assert result["api_url"] == "https://gitlab.internal.example/api/v4"
    assert "%2F" in urls[0]
    assert result["changed_files"] == ["models/fct_orders.sql"]


def test_github_comment_is_deduped_by_review_signature(monkeypatch):
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "not-a-real-token")

    def transport(method, url, headers, payload):
        return {"http_status": 200, "body": [{"id": 99, "body": "Signature: abc123\n<!-- agentic-data-engineering-review -->"}]}

    result = sync_github_review_comment(REVIEW, repository="acme/analytics", pull_number=4, token_env="TEST_GITHUB_TOKEN", transport=transport)
    assert result["status"] == "PASS"
    assert result["action"] == "DEDUPED"
    assert result["comment_id"] == 99


def test_github_comment_updates_previous_agentic_comment(monkeypatch):
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "not-a-real-token")
    calls = []

    def transport(method, url, headers, payload):
        calls.append((method, url, payload))
        if method == "GET":
            return {"http_status": 200, "body": [{"id": 41, "body": "Signature: old\n<!-- agentic-data-engineering-review -->"}]}
        return {"http_status": 200, "body": {"id": 41}}

    result = sync_github_review_comment(REVIEW, repository="acme/analytics", pull_number=4, token_env="TEST_GITHUB_TOKEN", transport=transport)
    assert result["action"] == "UPDATED"
    assert calls[-1][0] == "PATCH"
    assert calls[-1][1].endswith("/repos/acme/analytics/issues/comments/41")
    assert "Signature: abc123" in calls[-1][2]["body"]


def test_gitlab_note_updates_on_self_hosted_instance(monkeypatch):
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "not-a-real-token")
    calls = []

    def transport(method, url, headers, payload):
        calls.append((method, url, payload))
        if method == "GET":
            return {"http_status": 200, "body": [{"id": 5, "body": "Signature: old\n<!-- agentic-data-engineering-review -->"}]}
        return {"http_status": 200, "body": {"id": 5}}

    result = sync_gitlab_review_note(REVIEW, project="team/analytics", merge_request_iid=9, token_env="TEST_GITLAB_TOKEN", api_url="https://git.example/api/v4", transport=transport)
    assert result["status"] == "PASS"
    assert result["action"] == "UPDATED"
    assert calls[-1][0] == "PUT"
    assert calls[-1][1].endswith("/notes/5")


def test_missing_review_credentials_are_skip_external(monkeypatch):
    monkeypatch.delenv("NO_SUCH_GITHUB_TOKEN", raising=False)
    result = discover_github_pull("acme/analytics", 1, token_env="NO_SUCH_GITHUB_TOKEN")
    assert result == {"status": "SKIP_EXTERNAL", "provider": "github", "reason": "NO_SUCH_GITHUB_TOKEN is not configured"}


def test_github_changed_file_discovery_paginates(monkeypatch):
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "not-a-real-token")
    seen = []

    def transport(method, url, headers, payload):
        seen.append(url)
        if "/files?" in url:
            if "page=2" in url:
                return {"http_status": 200, "body": [{"filename": "models/final.sql"}]}
            return {
                "http_status": 200,
                "body": [{"filename": f"models/model_{index}.sql"} for index in range(100)],
            }
        return {
            "http_status": 200,
            "body": {"title": "large dbt change", "state": "open", "base": {"sha": "b"}, "head": {"sha": "h"}},
        }

    result = discover_github_pull(
        "acme/analytics",
        42,
        token_env="TEST_GITHUB_TOKEN",
        transport=transport,
    )
    assert result["status"] == "PASS"
    assert len(result["changed_files"]) == 101
    assert result["changed_files"][-1] == "models/final.sql"
    assert any("page=2" in url for url in seen)


def test_review_auth_failure_is_classified(monkeypatch):
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "not-a-real-token")

    def transport(method, url, headers, payload):
        return {"http_status": 401, "body": {"message": "Bad credentials"}}

    result = discover_github_pull(
        "acme/analytics",
        1,
        token_env="TEST_GITHUB_TOKEN",
        transport=transport,
    )
    assert result["status"] == "FAIL"
    assert result["error_type"] == "AUTHENTICATION_FAILURE"


def test_review_provider_outage_is_classified(monkeypatch):
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "not-a-real-token")

    def transport(method, url, headers, payload):
        return {"http_status": 503, "body": {"message": "unavailable"}}

    result = discover_gitlab_merge_request(
        "team/analytics",
        2,
        token_env="TEST_GITLAB_TOKEN",
        transport=transport,
    )
    assert result["status"] == "FAIL"
    assert result["error_type"] == "PROVIDER_OUTAGE"


def test_self_hosted_review_url_rejects_embedded_credentials(monkeypatch):
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "not-a-real-token")
    import pytest

    with pytest.raises(ValueError, match="embedded credentials"):
        discover_gitlab_merge_request(
            "team/analytics",
            3,
            token_env="TEST_GITLAB_TOKEN",
            api_url="https://user:password@gitlab.internal.example/api/v4",  # audit-safe-fixture
            transport=lambda *args: {"http_status": 200, "body": {}},
        )


def test_gitlab_note_discovery_paginates(monkeypatch):
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "not-a-real-token")
    seen = []

    def transport(method, url, headers, payload):
        seen.append((method, url))
        if method == "GET":
            if "page=2" in url:
                return {"http_status": 200, "body": []}
            return {
                "http_status": 200,
                "body": [{"id": index, "body": "human note"} for index in range(100)],
            }
        return {"http_status": 201, "body": {"id": 101}}

    result = sync_gitlab_review_note(
        REVIEW,
        project="team/analytics",
        merge_request_iid=9,
        token_env="TEST_GITLAB_TOKEN",
        transport=transport,
    )
    assert result["status"] == "PASS"
    assert result["action"] == "CREATED"
    assert any("page=2" in url for method, url in seen if method == "GET")
