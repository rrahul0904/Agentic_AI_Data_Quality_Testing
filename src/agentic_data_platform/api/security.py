from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import json
import os
import secrets
from typing import Any

from starlette.responses import JSONResponse

from agentic_data_platform.models import ActorMode


@dataclass(frozen=True)
class ApiPrincipal:
    subject: str
    role: ActorMode
    key_id: str


_CURRENT_PRINCIPAL: ContextVar[ApiPrincipal | None] = ContextVar(
    "ade_api_principal",
    default=None,
)

_ROLE_LEVEL = {
    ActorMode.ANALYST: 1,
    ActorMode.ASK: 1,
    ActorMode.PLAN: 1,
    ActorMode.BUILDER: 2,
    ActorMode.ADMIN: 3,
}


def production_mode() -> bool:
    return os.getenv("ADE_RUNTIME_MODE", "demo").strip().casefold() in {
        "prod",
        "production",
    }


def auth_required() -> bool:
    mode = os.getenv("ADE_AUTH_MODE", "disabled").strip().casefold()
    return production_mode() or mode == "api_key"


def _credentials() -> dict[str, ApiPrincipal]:
    raw = os.getenv("ADE_API_KEYS_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ADE_API_KEYS_JSON must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ADE_API_KEYS_JSON must be an object keyed by key id")

    credentials: dict[str, ApiPrincipal] = {}
    for key_id, item in payload.items():
        if not isinstance(item, dict):
            raise RuntimeError("each ADE_API_KEYS_JSON entry must be an object")
        token = str(item.get("token") or "")
        subject = str(item.get("subject") or key_id)
        role_value = str(item.get("role") or "analyst").casefold()
        try:
            role = ActorMode(role_value)
        except ValueError as exc:
            raise RuntimeError(f"invalid API role for key {key_id}: {role_value}") from exc
        if role in {ActorMode.ASK, ActorMode.PLAN}:
            role = ActorMode.ANALYST
        if not token:
            raise RuntimeError(f"API key {key_id} is missing token")
        if len(token) < 24:
            raise RuntimeError(f"API key {key_id} token must be at least 24 characters")
        credentials[token] = ApiPrincipal(subject=subject, role=role, key_id=str(key_id))
    return credentials


def validate_runtime_configuration() -> None:
    auth_mode = os.getenv("ADE_AUTH_MODE", "disabled").strip().casefold()
    if auth_mode not in {"disabled", "api_key"}:
        raise RuntimeError("ADE_AUTH_MODE must be disabled or api_key")

    if production_mode():
        if os.getenv("ADE_DEMO_MODE", "true").strip().casefold() != "false":
            raise RuntimeError("production runtime requires ADE_DEMO_MODE=false")
        if auth_mode != "api_key":
            raise RuntimeError("production runtime requires ADE_AUTH_MODE=api_key")

    if auth_required() and not _credentials():
        raise RuntimeError("authenticated runtime requires ADE_API_KEYS_JSON")


def current_principal() -> ApiPrincipal:
    principal = _CURRENT_PRINCIPAL.get()
    if principal is not None:
        return principal
    if not auth_required():
        return ApiPrincipal(
            subject="local-dev",
            role=ActorMode.ADMIN,
            key_id="local-dev",
        )
    raise PermissionError("authenticated API principal required")


def require_actor_mode(requested: ActorMode) -> ApiPrincipal:
    principal = current_principal()
    if _ROLE_LEVEL[requested] > _ROLE_LEVEL[principal.role]:
        raise PermissionError(
            f"principal role {principal.role.value} cannot assume {requested.value}"
        )
    return principal


def require_role(required: ActorMode) -> ApiPrincipal:
    principal = current_principal()
    if _ROLE_LEVEL[principal.role] < _ROLE_LEVEL[required]:
        raise PermissionError(
            f"principal role {principal.role.value} requires {required.value}"
        )
    return principal


def _principal_for_authorization(value: str) -> ApiPrincipal | None:
    scheme, _, token = value.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        return None
    for configured_token, principal in _credentials().items():
        if secrets.compare_digest(configured_token, token):
            return principal
    return None


class ApiKeyAuthMiddleware:
    """Authenticate API requests before they can reach governed tool routes."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if path == "/healthz":
            await self.app(scope, receive, send)
            return

        if not auth_required():
            token = _CURRENT_PRINCIPAL.set(
                ApiPrincipal(
                    subject="local-dev",
                    role=ActorMode.ADMIN,
                    key_id="local-dev",
                )
            )
            try:
                await self.app(scope, receive, send)
            finally:
                _CURRENT_PRINCIPAL.reset(token)
            return

        headers = {
            key.decode("latin1").casefold(): value.decode("latin1")
            for key, value in scope.get("headers") or []
        }
        principal = _principal_for_authorization(headers.get("authorization", ""))
        if principal is None:
            response = JSONResponse(
                {
                    "status": "UNAUTHORIZED",
                    "detail": "valid bearer API credential required",
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        token = _CURRENT_PRINCIPAL.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _CURRENT_PRINCIPAL.reset(token)
