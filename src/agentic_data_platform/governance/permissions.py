"""Provider-neutral least-privilege permission administration contracts."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Mapping

from agentic_data_platform.connectors.base import DataPlatformConnector


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$.-]{0,255}$")
_PRIVILEGES = {
    "select", "insert", "update", "delete", "usage", "create", "monitor",
    "operate", "references", "read", "write", "all",
}
_ACTIONS = {"grant_privilege", "revoke_privilege", "grant_role", "revoke_role"}


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _ident(value: str, *, field: str) -> str:
    text = str(value).strip()
    if not _IDENT.fullmatch(text):
        raise ValueError(f"invalid {field}: {value}")
    return text


def _privilege(value: str) -> str:
    item = str(value).strip().casefold()
    if item not in _PRIVILEGES:
        raise ValueError(f"unsupported privilege: {value}")
    return item.upper()


def _platform(value: str) -> str:
    platform = str(value).casefold().replace("_", "-")
    aliases = {
        "postgresql": "postgres",
        "k8s": "kubernetes",
        "spark": "databricks",
    }
    return aliases.get(platform, platform)


def _statement(
    *,
    platform: str,
    action: str,
    principal: str,
    principal_kind: str,
    privilege: str | None,
    object_type: str | None,
    object_name: str | None,
    role: str | None,
) -> tuple[str, str]:
    platform = _platform(platform)
    action = str(action).casefold()
    principal = _ident(principal, field="principal")
    principal_kind = str(principal_kind).casefold()
    if principal_kind not in {"user", "role"}:
        raise ValueError("principal_kind must be user or role")

    if action in {"grant_role", "revoke_role"}:
        role_name = _ident(str(role or ""), field="role")
        verb = "GRANT" if action == "grant_role" else "REVOKE"
        if platform == "snowflake":
            statement = (
                f"{verb} ROLE {role_name} "
                f"{'TO' if verb == 'GRANT' else 'FROM'} {principal_kind.upper()} {principal}"
            )
            verify = (
                f"SHOW GRANTS TO {principal_kind.upper()} {principal}"
            )
        elif platform in {"postgres", "redshift"}:
            if principal_kind != "user":
                raise ValueError(f"{platform} role membership target must be a user/role principal name")
            statement = f"{verb} {role_name} {'TO' if verb == 'GRANT' else 'FROM'} {principal}"
            verify = (
                "SELECT rolname FROM pg_roles "
                f"WHERE rolname = '{role_name}'"
            )
        elif platform == "databricks":
            statement = (
                f"{verb} ROLE {role_name} "
                f"{'TO' if verb == 'GRANT' else 'FROM'} {principal_kind.upper()} {principal}"
            )
            verify = f"SHOW GRANTS TO {principal_kind.upper()} {principal}"
        else:
            raise ValueError(f"permission planning unsupported for platform: {platform}")
        return statement, verify

    privilege_name = _privilege(str(privilege or ""))
    obj_type = _ident(str(object_type or ""), field="object_type").upper()
    obj_name = _ident(str(object_name or ""), field="object_name")
    verb = "GRANT" if action == "grant_privilege" else "REVOKE"

    if platform == "snowflake":
        statement = (
            f"{verb} {privilege_name} ON {obj_type} {obj_name} "
            f"{'TO' if verb == 'GRANT' else 'FROM'} {principal_kind.upper()} {principal}"
        )
        verify = f"SHOW GRANTS TO {principal_kind.upper()} {principal}"
    elif platform in {"postgres", "redshift"}:
        statement = (
            f"{verb} {privilege_name} ON {obj_type} {obj_name} "
            f"{'TO' if verb == 'GRANT' else 'FROM'} {principal}"
        )
        verify = (
            "SELECT grantee, privilege_type FROM information_schema.role_table_grants "
            f"WHERE grantee = '{principal}'"
        )
    elif platform == "databricks":
        statement = (
            f"{verb} {privilege_name} ON {obj_type} {obj_name} "
            f"{'TO' if verb == 'GRANT' else 'FROM'} {principal_kind.upper()} {principal}"
        )
        verify = f"SHOW GRANTS ON {obj_type} {obj_name}"
    else:
        raise ValueError(f"permission planning unsupported for platform: {platform}")
    return statement, verify


def permission_change_plan(
    *,
    platform: str,
    action: str,
    principal: str,
    principal_kind: str = "role",
    privilege: str | None = None,
    object_type: str | None = None,
    object_name: str | None = None,
    role: str | None = None,
    environment: str = "dev",
    reason: str | None = None,
    observed_graph: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    action_key = str(action).casefold()
    if action_key not in _ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(sorted(_ACTIONS))}")
    env = str(environment).casefold()
    if env not in {"dev", "staging", "prod"}:
        raise ValueError("environment must be dev, staging, or prod")
    statement, verification_sql = _statement(
        platform=platform,
        action=action_key,
        principal=principal,
        principal_kind=principal_kind,
        privilege=privilege,
        object_type=object_type,
        object_name=object_name,
        role=role,
    )
    destructive = action_key.startswith("revoke")
    blast_radius = {
        "principal": principal,
        "principal_kind": principal_kind,
        "object": object_name,
        "role": role,
        "observed_graph_supplied": observed_graph is not None,
        "reachable_access_before": None,
    }
    if observed_graph is not None:
        from agentic_data_platform.governance.rbac import reachable_access

        try:
            reachable = reachable_access(
                observed_graph,
                str(principal_kind),
                str(principal),
            )
            blast_radius["reachable_access_before"] = reachable["access_count"]
        except KeyError:
            blast_radius["reachable_access_before"] = 0

    payload = {
        "platform": _platform(platform),
        "action": action_key,
        "principal": principal,
        "principal_kind": principal_kind,
        "privilege": privilege,
        "object_type": object_type,
        "object_name": object_name,
        "role": role,
        "environment": env,
        "statement": statement,
        "verification_sql": verification_sql,
        "reason": reason,
        "destructive": destructive,
        "blast_radius": blast_radius,
    }
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        **payload,
        "approval_fingerprint": _digest(payload),
        "least_privilege": {
            "single_principal": True,
            "single_role_or_object": True,
            "wildcard_principal": False,
            "explicit_privilege": privilege is not None if action_key.endswith("privilege") else True,
        },
        "policy": {
            "approval_required": True,
            "independent_verification_required": True,
            "production_revoke_requires_admin": destructive and env == "prod",
        },
    }



def _casefold_row(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key).casefold(): str(value).casefold()
        for key, value in row.items()
        if value is not None
    }


def _verification_matches(
    plan: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    action = str(plan["action"]).casefold()
    principal = str(plan["principal"]).casefold()
    role = str(plan.get("role") or "").casefold()
    privilege = str(plan.get("privilege") or "").casefold()
    object_name = str(plan.get("object_name") or "").casefold()
    matches: list[dict[str, Any]] = []

    for raw in rows:
        row = _casefold_row(raw)
        grantee = (
            row.get("grantee_name")
            or row.get("grantee")
            or row.get("user_name")
            or row.get("principal")
            or ""
        )
        if grantee and grantee != principal:
            continue

        if action in {"grant_role", "revoke_role"}:
            granted_role = (
                row.get("role")
                or row.get("granted_role")
                or row.get("name")
                or row.get("rolname")
                or ""
            )
            if granted_role == role:
                matches.append(dict(raw))
            continue

        row_privilege = (
            row.get("privilege")
            or row.get("privilege_type")
            or ""
        )
        row_object = (
            row.get("name")
            or row.get("object_name")
            or row.get("table_name")
            or row.get("object")
            or ""
        )
        object_match = row_object == object_name or row_object.endswith("." + object_name)
        if row_privilege == privilege and object_match:
            matches.append(dict(raw))
    return matches


def _verify_permission_state(
    plan: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    matches = _verification_matches(plan, rows)
    expected_present = str(plan["action"]).casefold().startswith("grant")
    observed_present = bool(matches)
    passed = observed_present if expected_present else not observed_present
    return {
        "status": "PASS" if passed else "FAIL",
        "expected_present": expected_present,
        "observed_present": observed_present,
        "match_count": len(matches),
        "matches": matches[:100],
    }


def execute_permission_change(
    connector: DataPlatformConnector,
    plan: Mapping[str, Any],
    *,
    approval_fingerprint: str,
    actor_mode: str = "builder",
) -> dict[str, Any]:
    payload = {
        key: plan[key]
        for key in (
            "platform", "action", "principal", "principal_kind", "privilege",
            "object_type", "object_name", "role", "environment", "statement",
            "verification_sql", "reason", "destructive", "blast_radius",
        )
    }
    expected = _digest(payload)
    if approval_fingerprint != expected or plan.get("approval_fingerprint") != expected:
        return {"status": "STALE_APPROVAL", "approval_fingerprint": expected}
    if str(plan["platform"]) != str(connector.platform):
        return {
            "status": "BLOCKED_PLATFORM_MISMATCH",
            "planned_platform": plan["platform"],
            "connector_platform": connector.platform,
        }
    if bool(plan.get("destructive")) and str(plan.get("environment")) == "prod":
        if str(actor_mode).casefold() != "admin":
            return {
                "status": "BLOCKED_POLICY",
                "reason": "production permission revocation requires admin actor mode",
            }

    executor = getattr(connector, "execute_governed_mutation", None)
    if not callable(executor):
        return {
            "status": "BLOCKED_UNSUPPORTED",
            "platform": connector.platform,
            "reason": (
                "connector does not expose execute_governed_mutation; "
                "read-only connector contract remains intact"
            ),
        }

    mutation = executor(str(plan["statement"]))
    try:
        verification = connector.execute_read(str(plan["verification_sql"]))
        verify_rows = [dict(row) for row in verification.rows]
        state = _verify_permission_state(plan, verify_rows)
        verify_status = state["status"]
        verify_error = None
    except Exception as exc:
        verify_rows = []
        state = {
            "status": "FAIL",
            "expected_present": str(plan["action"]).casefold().startswith("grant"),
            "observed_present": False,
            "match_count": 0,
            "matches": [],
        }
        verify_status = "FAIL"
        verify_error = f"{type(exc).__name__}: {exc}"

    evidence = {
        "statement_sha256": sha256(str(plan["statement"]).encode("utf-8")).hexdigest(),
        "verification_sql_sha256": sha256(str(plan["verification_sql"]).encode("utf-8")).hexdigest(),
        "verification_row_count": len(verify_rows),
        "verification_rows": verify_rows[:100],
        "verification_state": state,
        "mutation_query_id": getattr(mutation, "query_id", None),
    }
    return {
        "status": "PASS" if verify_status == "PASS" else "FAIL_VERIFY",
        "platform": connector.platform,
        "action": plan["action"],
        "verification_status": verify_status,
        "verification_error": verify_error,
        "evidence": evidence,
        "evidence_fingerprint": _digest(evidence),
        "approval_fingerprint": expected,
    }
