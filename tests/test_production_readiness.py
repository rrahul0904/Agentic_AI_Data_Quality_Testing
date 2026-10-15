from __future__ import annotations

from scripts.production_readiness import evaluate, report


def _base_env() -> dict[str, str]:
    web_token = "w" * 32
    return {
        "ADE_COMMIT_SHA": "a" * 40,
        "ADE_API_KEYS_JSON": (
            '{"web":{"token":"' + web_token + '","subject":"ade-web","role":"analyst"},'
            '"admin":{"token":"' + ("x" * 32) + '","subject":"ade-admin","role":"admin"}}'
        ),
        "ADE_API_SERVICE_TOKEN": web_token,
        "ADE_WEB_USERS_JSON": '{"operator":"' + ("z" * 32) + '"}',
        "ADE_PROJECT_SOURCE_MODE": "git",
        "ADE_PROJECT_GIT_URL": "https://github.com/acme/data-platform.git",
        "ADE_PROJECT_GIT_REF": "0123456789abcdef0123456789abcdef01234567",
        "ADE_BILLING_ENFORCEMENT": "required",
        "ADE_STRIPE_SECRET_KEY": "sk_live_configured",
        "ADE_STRIPE_WEBHOOK_SECRET": "whsec_configured",
        "ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY": "price_123",
        "ADE_BILLING_ALLOWED_RETURN_ORIGINS": "https://ade.example.com",
        "ADE_DATABASE_URL": "postgresql://configured",
        "ADE_ARTIFACT_STORE_MODE": "s3",
    }


def test_production_readiness_passes_complete_hosted_configuration() -> None:
    payload = report(evaluate(_base_env()))
    assert payload["ready"] is True
    assert payload["failure_count"] == 0


def test_production_readiness_rejects_placeholder_credentials() -> None:
    env = _base_env()
    env["ADE_WEB_USERS_JSON"] = '{"operator":"replace-with-a-long-random-password"}'
    payload = report(evaluate(env))
    assert payload["ready"] is False
    assert any(
        item["name"] == "web_credentials" and item["status"] == "FAIL"
        for item in payload["checks"]
    )


def test_production_readiness_requires_service_token_to_match_principal() -> None:
    env = _base_env()
    env["ADE_API_SERVICE_TOKEN"] = "q" * 32
    payload = report(evaluate(env))
    assert payload["ready"] is False
    assert any(
        item["name"] == "web_service_token" and item["status"] == "FAIL"
        for item in payload["checks"]
    )


def test_production_readiness_rejects_http_paid_return_origin() -> None:
    env = _base_env()
    env["ADE_BILLING_ALLOWED_RETURN_ORIGINS"] = "http://ade.example.com"
    payload = report(evaluate(env))
    assert payload["ready"] is False
    assert any(
        item["name"] == "paid_billing" and item["status"] == "FAIL"
        for item in payload["checks"]
    )


def test_optional_billing_is_warning_not_failure() -> None:
    env = _base_env()
    env["ADE_BILLING_ENFORCEMENT"] = "optional"
    env["ADE_STRIPE_SECRET_KEY"] = ""
    env["ADE_STRIPE_WEBHOOK_SECRET"] = ""
    env["ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY"] = ""
    env["ADE_BILLING_ALLOWED_RETURN_ORIGINS"] = ""
    payload = report(evaluate(env))
    assert payload["ready"] is True
    assert any(
        item["name"] == "paid_billing" and item["status"] == "WARN"
        for item in payload["checks"]
    )
