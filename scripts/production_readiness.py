from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
import re
import sys
from typing import Mapping
from urllib.parse import urlparse


_SHA = re.compile(r"^[0-9a-f]{40}$")
_INSECURE_MARKERS = ("replace-with", "changeme", "example", "password")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _secret_is_strong(value: str, *, minimum: int = 24) -> bool:
    normalized = value.strip()
    if len(normalized) < minimum:
        return False
    lowered = normalized.casefold()
    return not any(marker in lowered for marker in _INSECURE_MARKERS)


def _json_object(value: str, name: str) -> tuple[dict[str, object] | None, Check | None]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None, Check(name, "FAIL", "must contain valid JSON")
    if not isinstance(payload, dict) or not payload:
        return None, Check(name, "FAIL", "must be a non-empty JSON object")
    return payload, None


def evaluate(env: Mapping[str, str] | None = None) -> list[Check]:
    values = os.environ if env is None else env
    checks: list[Check] = []

    sha = values.get("ADE_COMMIT_SHA", "").strip().casefold()
    checks.append(
        Check(
            "release_sha",
            "PASS" if _SHA.fullmatch(sha) else "FAIL",
            "exact 40-character Git SHA configured" if _SHA.fullmatch(sha) else "ADE_COMMIT_SHA must be an exact 40-character lowercase Git SHA",
        )
    )

    api_keys, api_error = _json_object(values.get("ADE_API_KEYS_JSON", ""), "api_credentials")
    if api_error:
        checks.append(api_error)
    else:
        invalid: list[str] = []
        assert api_keys is not None
        for key_id, entry in api_keys.items():
            if not isinstance(entry, dict) or not _secret_is_strong(str(entry.get("token") or "")):
                invalid.append(str(key_id))
        checks.append(
            Check(
                "api_credentials",
                "PASS" if not invalid else "FAIL",
                "API credentials are non-placeholder and sufficiently long" if not invalid else f"weak or placeholder API token(s): {', '.join(invalid)}",
            )
        )

    web_users, web_error = _json_object(values.get("ADE_WEB_USERS_JSON", ""), "web_credentials")
    if web_error:
        checks.append(web_error)
    else:
        weak_users: list[str] = []
        assert web_users is not None
        for username, password in web_users.items():
            if not _secret_is_strong(str(password)):
                weak_users.append(str(username))
        checks.append(
            Check(
                "web_credentials",
                "PASS" if not weak_users else "FAIL",
                "web credentials are non-placeholder and sufficiently long" if not weak_users else f"weak or placeholder web password(s): {', '.join(weak_users)}",
            )
        )

    service_token = values.get("ADE_API_SERVICE_TOKEN", "")
    configured_tokens = {
        str(entry.get("token") or "")
        for entry in (api_keys or {}).values()
        if isinstance(entry, dict)
    }
    checks.append(
        Check(
            "web_service_token",
            "PASS" if _secret_is_strong(service_token) and service_token in configured_tokens else "FAIL",
            "web service token maps to a configured API principal" if _secret_is_strong(service_token) and service_token in configured_tokens else "ADE_API_SERVICE_TOKEN must be a strong token present in ADE_API_KEYS_JSON",
        )
    )

    source_mode = values.get("ADE_PROJECT_SOURCE_MODE", "embedded_demo").strip().casefold()
    if source_mode == "git":
        git_url = values.get("ADE_PROJECT_GIT_URL", "").strip()
        git_ref = values.get("ADE_PROJECT_GIT_REF", "").strip()
        parsed = urlparse(git_url)
        safe_git = parsed.scheme == "https" and bool(parsed.netloc) and bool(git_ref)
        checks.append(
            Check(
                "project_source",
                "PASS" if safe_git else "FAIL",
                "managed Git source uses HTTPS with an explicit ref" if safe_git else "git project source requires an HTTPS URL and explicit ADE_PROJECT_GIT_REF",
            )
        )
    elif source_mode == "embedded_demo":
        checks.append(Check("project_source", "WARN", "embedded demo project is configured; use a managed immutable Git ref for customer workloads"))
    else:
        checks.append(Check("project_source", "FAIL", f"unsupported ADE_PROJECT_SOURCE_MODE={source_mode!r}"))

    billing_mode = values.get("ADE_BILLING_ENFORCEMENT", "optional").strip().casefold()
    if billing_mode not in {"disabled", "optional", "required"}:
        checks.append(Check("billing_mode", "FAIL", "ADE_BILLING_ENFORCEMENT must be disabled, optional, or required"))
    elif billing_mode == "required":
        required = {
            "ADE_STRIPE_SECRET_KEY": values.get("ADE_STRIPE_SECRET_KEY", ""),
            "ADE_STRIPE_WEBHOOK_SECRET": values.get("ADE_STRIPE_WEBHOOK_SECRET", ""),
            "ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY": values.get("ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY", ""),
        }
        missing = [name for name, value in required.items() if not value.strip()]
        origin = values.get("ADE_BILLING_ALLOWED_RETURN_ORIGINS", "").strip()
        origins = [item.strip() for item in origin.split(",") if item.strip()]
        unsafe_origins = [item for item in origins if urlparse(item).scheme != "https" or not urlparse(item).netloc]
        if not origins:
            missing.append("ADE_BILLING_ALLOWED_RETURN_ORIGINS")
        checks.append(
            Check(
                "paid_billing",
                "PASS" if not missing and not unsafe_origins else "FAIL",
                "paid entitlement enforcement has Stripe and HTTPS return-origin configuration" if not missing and not unsafe_origins else f"missing={missing or 'none'} unsafe_origins={unsafe_origins or 'none'}",
            )
        )
    else:
        checks.append(Check("paid_billing", "WARN", f"billing enforcement is {billing_mode}; hosted APIs are not hard-paywalled"))

    artifact_mode = values.get("ADE_ARTIFACT_STORE_MODE", "filesystem").strip().casefold()
    database_url = values.get("ADE_DATABASE_URL", "").strip()
    if artifact_mode == "filesystem" or not database_url:
        checks.append(Check("ha_persistence", "WARN", "single-node persistence is configured; use managed PostgreSQL and object storage for multi-node SaaS"))
    else:
        checks.append(Check("ha_persistence", "PASS", "external control-plane database and non-filesystem artifact mode are configured"))

    return checks


def report(checks: list[Check]) -> dict[str, object]:
    failures = [item for item in checks if item.status == "FAIL"]
    warnings = [item for item in checks if item.status == "WARN"]
    return {
        "schema_version": "ade-production-readiness/1.0",
        "ready": not failures,
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "checks": [asdict(item) for item in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed ADE production readiness validation")
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args()

    payload = report(evaluate())
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        from pathlib import Path

        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
    sys.stdout.write(rendered)
    return 0 if payload["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
