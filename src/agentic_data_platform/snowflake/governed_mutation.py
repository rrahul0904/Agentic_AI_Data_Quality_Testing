"""Governed Snowflake mutation planning, approval binding, execution, and verification.

The agent may propose SQL, but deterministic controls decide whether it is
eligible to run. Normal warehouse connectors remain read-only by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
import re
from typing import Any

from agentic_data_platform.connectors.snowflake import SnowflakeConnector
from agentic_data_platform.sql.parser import parse_sql
from agentic_data_platform.sql.safety import validate_single_statement


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(PASSWORD|TOKEN|SECRET|AWS_KEY_ID|AWS_SECRET_KEY|CLIENT_SECRET)\s*=\s*('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[^\s,)]+)"
)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_SPACE = re.compile(r"\s+")
_CREATE = re.compile(
    r"(?is)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TRANSIENT\s+|TEMP(?:ORARY)?\s+)?"
    r"(MATERIALIZED\s+VIEW|FILE\s+FORMAT|DBT\s+PROJECT|MODEL|TABLE|VIEW|STREAM|STAGE|PIPE|TASK|WAREHOUSE|DATABASE|SCHEMA|ROLE|USER|INTEGRATION)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([^\s(;]+)"
)
_ALTER = re.compile(
    r"(?is)^\s*ALTER\s+(TABLE|VIEW|STREAM|STAGE|PIPE|TASK|WAREHOUSE|DATABASE|SCHEMA|ROLE|USER|INTEGRATION|DBT\s+PROJECT|MODEL)\s+"
    r"(?:IF\s+EXISTS\s+)?([^\s(;]+)"
)
_DROP = re.compile(
    r"(?is)^\s*DROP\s+(TABLE|VIEW|MATERIALIZED\s+VIEW|STREAM|STAGE|PIPE|TASK|WAREHOUSE|DATABASE|SCHEMA|ROLE|USER|INTEGRATION|DBT\s+PROJECT|MODEL)\s+"
    r"(?:IF\s+EXISTS\s+)?([^\s(;]+)"
)
_ALTER_MODEL_DROP_VERSION = re.compile(r"(?is)^\s*ALTER\s+MODEL\s+(?:IF\s+EXISTS\s+)?([^\s(;]+)\s+DROP\s+VERSION\s+([^\s;]+)")
_TRUNCATE = re.compile(r"(?is)^\s*TRUNCATE\s+(?:TABLE\s+)?([^\s(;]+)")
_INSERT = re.compile(r"(?is)^\s*INSERT\s+INTO\s+([^\s(;]+)")
_UPDATE = re.compile(r"(?is)^\s*UPDATE\s+([^\s(;]+)")
_DELETE = re.compile(r"(?is)^\s*DELETE\s+FROM\s+([^\s(;]+)")
_MERGE = re.compile(r"(?is)^\s*MERGE\s+INTO\s+([^\s(;]+)")
_COPY = re.compile(r"(?is)^\s*COPY\s+INTO\s+([^\s(;]+)")
_GRANT = re.compile(r"(?is)^\s*GRANT\b")
_REVOKE = re.compile(r"(?is)^\s*REVOKE\b")
_USE = re.compile(r"(?is)^\s*USE\s+(ROLE|WAREHOUSE|DATABASE|SCHEMA)\s+([^\s;]+)")
_CALL = re.compile(r"(?is)^\s*CALL\s+([^\s(;]+)")
_EXECUTE_DBT = re.compile(r"(?is)^\s*EXECUTE\s+DBT\s+PROJECT(?:\s+IF\s+EXISTS)?(?:\s+FROM\s+WORKSPACE)?\s+([^\s;]+)")


@dataclass(frozen=True)
class MutationDescriptor:
    statement_type: str
    object_type: str | None
    target: str | None
    risk_level: str
    destructive: bool


def _normalize(sql: str) -> str:
    """Canonicalize SQL without changing quoted literal/identifier content.

    Approval fingerprints must distinguish statements whose string literals differ.
    SQL comments and insignificant whitespace are normalized only outside quoted
    regions. This prevents values such as dbt ARGS='build --select model_a' from
    being mistaken for a line comment.
    """
    text = str(sql or "")
    output: list[str] = []
    index = 0
    pending_space = False
    state = "normal"
    dollar_tag: str | None = None

    def flush_space() -> None:
        nonlocal pending_space
        if pending_space and output and output[-1] != " ":
            output.append(" ")
        pending_space = False

    while index < len(text):
        char = text[index]

        if state == "single":
            output.append(char)
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    output.append(text[index + 1])
                    index += 2
                    continue
                state = "normal"
            index += 1
            continue

        if state == "double":
            output.append(char)
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    output.append(text[index + 1])
                    index += 2
                    continue
                state = "normal"
            index += 1
            continue

        if state == "dollar":
            assert dollar_tag is not None
            if text.startswith(dollar_tag, index):
                output.append(dollar_tag)
                index += len(dollar_tag)
                state = "normal"
                dollar_tag = None
                continue
            output.append(char)
            index += 1
            continue

        if char.isspace():
            pending_space = True
            index += 1
            continue

        if text.startswith("--", index):
            pending_space = True
            newline = text.find("\n", index + 2)
            if newline < 0:
                break
            index = newline + 1
            continue

        if text.startswith("/*", index):
            pending_space = True
            end = text.find("*/", index + 2)
            if end < 0:
                # Treat an unterminated trailing comment as comment text. The SQL
                # parser/executor remains responsible for rejecting malformed SQL.
                break
            index = end + 2
            continue

        if char == "'":
            flush_space()
            output.append(char)
            state = "single"
            index += 1
            continue

        if char == '"':
            flush_space()
            output.append(char)
            state = "double"
            index += 1
            continue

        if char == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", text[index:])
            if match:
                flush_space()
                dollar_tag = match.group(0)
                output.append(dollar_tag)
                index += len(dollar_tag)
                state = "dollar"
                continue

        flush_space()
        output.append(char)
        index += 1

    canonical = "".join(output).strip()
    if canonical.endswith(";"):
        canonical = canonical[:-1].rstrip()
    return canonical


def _redact(sql: str) -> str:
    return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}='***REDACTED***'", str(sql))


def _clean_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"[]')
    if cleaned.startswith(chr(96)) and cleaned.endswith(chr(96)):
        cleaned = cleaned[1:-1]
    return cleaned


def _object_parts(target: str | None) -> tuple[str | None, str | None]:
    if not target:
        return None, None
    cleaned = _clean_identifier(target) or ""
    parts = [part.strip('"') for part in cleaned.split(".") if part]
    if not parts:
        return None, None
    return (".".join(parts[:-1]) or None, parts[-1])


def _describe(sql: str) -> MutationDescriptor:
    normalized = _normalize(sql)

    match = _CREATE.match(normalized)
    if match:
        object_type = match.group(1).upper().replace(" ", "_")
        destructive = bool(re.match(r"(?is)^\s*CREATE\s+OR\s+REPLACE\b", normalized))
        return MutationDescriptor(
            "CREATE_OR_REPLACE" if destructive else "CREATE",
            object_type,
            _clean_identifier(match.group(2)),
            "destructive" if destructive else "safe_create",
            destructive,
        )

    match = _ALTER.match(normalized)
    if match:
        return MutationDescriptor(
            "ALTER",
            match.group(1).upper().replace(" ", "_"),
            _clean_identifier(match.group(2)),
            "schema_or_platform_change",
            False,
        )

    match = _DROP.match(normalized)
    if match:
        return MutationDescriptor(
            "DROP",
            match.group(1).upper().replace(" ", "_"),
            _clean_identifier(match.group(2)),
            "destructive",
            True,
        )

    match = _TRUNCATE.match(normalized)
    if match:
        return MutationDescriptor("TRUNCATE", "TABLE", _clean_identifier(match.group(1)), "destructive", True)

    for regex, statement in (
        (_INSERT, "INSERT"),
        (_UPDATE, "UPDATE"),
        (_MERGE, "MERGE"),
        (_COPY, "COPY_INTO"),
    ):
        match = regex.match(normalized)
        if match:
            return MutationDescriptor(statement, "TABLE", _clean_identifier(match.group(1)), "data_change", False)

    match = _DELETE.match(normalized)
    if match:
        destructive = not bool(re.search(r"(?is)\bWHERE\b", normalized))
        return MutationDescriptor(
            "DELETE",
            "TABLE",
            _clean_identifier(match.group(1)),
            "destructive" if destructive else "data_change",
            destructive,
        )

    match = _USE.match(normalized)
    if match:
        return MutationDescriptor(
            "USE",
            match.group(1).upper(),
            _clean_identifier(match.group(2)),
            "session_change",
            False,
        )

    match = _CALL.match(normalized)
    if match:
        return MutationDescriptor(
            "CALL",
            "PROCEDURE",
            _clean_identifier(match.group(1)),
            "procedure_call",
            False,
        )

    match = _EXECUTE_DBT.match(normalized)
    if match:
        return MutationDescriptor(
            "EXECUTE_DBT_PROJECT",
            "DBT_PROJECT",
            None,
            "data_change",
            False,
        )

    if _GRANT.match(normalized):
        return MutationDescriptor("GRANT", "PRIVILEGE", None, "security_change", False)

    if _REVOKE.match(normalized):
        return MutationDescriptor("REVOKE", "PRIVILEGE", None, "security_change", True)

    ast = parse_sql(normalized, "snowflake")
    if not ast.ddl_operations and not ast.dml_operations:
        raise ValueError("statement is read-only; use the read-only SQL tool instead")
    raise ValueError("unsupported Snowflake mutation statement")


def _fingerprint(sql: str, environment: str, descriptor: MutationDescriptor) -> str:
    material = "|".join(
        (
            _normalize(sql),
            str(environment).casefold(),
            descriptor.statement_type,
            descriptor.object_type or "",
            descriptor.target or "",
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _show_command(descriptor: MutationDescriptor) -> str | None:
    if not descriptor.object_type or not descriptor.target:
        return None
    parent, leaf = _object_parts(descriptor.target)
    object_type = descriptor.object_type
    show_map = {
        "TABLE": "TABLES",
        "VIEW": "VIEWS",
        "MATERIALIZED_VIEW": "MATERIALIZED VIEWS",
        "STREAM": "STREAMS",
        "STAGE": "STAGES",
        "PIPE": "PIPES",
        "TASK": "TASKS",
        "MODEL": "MODELS",
        "WAREHOUSE": "WAREHOUSES",
        "DATABASE": "DATABASES",
        "SCHEMA": "SCHEMAS",
        "ROLE": "ROLES",
        "USER": "USERS",
        "INTEGRATION": "INTEGRATIONS",
        "FILE_FORMAT": "FILE FORMATS",
        "DBT_PROJECT": "DBT PROJECTS",
    }
    plural = show_map.get(object_type)
    if not plural or not leaf:
        return None
    escaped_leaf = leaf.replace("'", "''")
    command = f"SHOW {plural} LIKE '{escaped_leaf}'"
    if parent:
        if object_type == "SCHEMA":
            command += f" IN DATABASE {parent}"
        elif object_type not in {"WAREHOUSE", "DATABASE", "ROLE", "USER", "INTEGRATION"}:
            command += f" IN SCHEMA {parent}"
    return command


def _alter_table_expectation(sql: str) -> list[dict[str, Any]]:
    normalized = _normalize(sql)
    target_match = _ALTER.match(normalized)
    if not target_match or target_match.group(1).upper() != "TABLE":
        return []
    target = _clean_identifier(target_match.group(2))
    add = re.search(r"(?is)\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([\w$\"]+)", normalized)
    drop = re.search(r"(?is)\bDROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?([\w$\"]+)", normalized)
    rename = re.search(r"(?is)\bRENAME\s+COLUMN\s+([\w$\"]+)\s+TO\s+([\w$\"]+)", normalized)
    checks: list[dict[str, Any]] = []
    if add:
        checks.append({"kind": "column_presence", "sql": f"DESC TABLE {target}", "column": _clean_identifier(add.group(1)), "expect_present": True})
    if drop:
        checks.append({"kind": "column_presence", "sql": f"DESC TABLE {target}", "column": _clean_identifier(drop.group(1)), "expect_present": False})
    if rename:
        checks.extend([
            {"kind": "column_presence", "sql": f"DESC TABLE {target}", "column": _clean_identifier(rename.group(1)), "expect_present": False},
            {"kind": "column_presence", "sql": f"DESC TABLE {target}", "column": _clean_identifier(rename.group(2)), "expect_present": True},
        ])
    return checks


def _verification_plan(descriptor: MutationDescriptor, sql: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    show = _show_command(descriptor)
    if show:
        checks.append(
            {
                "kind": "object_presence",
                "sql": show,
                "expect_present": descriptor.statement_type != "DROP",
            }
        )

    if descriptor.statement_type == "ALTER" and descriptor.object_type == "TABLE":
        checks.extend(_alter_table_expectation(sql))

    if descriptor.statement_type == "TRUNCATE" and descriptor.target:
        checks.append(
            {
                "kind": "row_count",
                "sql": f"SELECT COUNT(*) AS ROW_COUNT FROM {descriptor.target}",
                "expected": 0,
            }
        )

    if descriptor.statement_type == "DELETE" and descriptor.destructive and descriptor.target:
        checks.append(
            {
                "kind": "row_count",
                "sql": f"SELECT COUNT(*) AS ROW_COUNT FROM {descriptor.target}",
                "expected": 0,
            }
        )

    if descriptor.statement_type in {"INSERT", "UPDATE", "DELETE", "MERGE", "COPY_INTO", "CALL", "GRANT", "REVOKE", "USE", "EXECUTE_DBT_PROJECT"}:
        checks.append(
            {
                "kind": "query_status",
                "sql": (
                    "SELECT query_id, query_type, execution_status, error_code, error_message, "
                    "rows_produced, rows_inserted, rows_updated, rows_deleted "
                    "FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION(RESULT_LIMIT => 10)) "
                    "ORDER BY start_time DESC LIMIT 10"
                ),
                "expect_execution_status": "SUCCESS",
            }
        )
    return checks


def plan_snowflake_mutation(sql: str, *, environment: str = "dev") -> dict[str, Any]:
    if not validate_single_statement(sql):
        return {
            "status": "FAIL",
            "code": "MULTI_STATEMENT_BLOCKED",
            "reason": "one governed mutation request may contain exactly one SQL statement",
        }

    descriptor = _describe(sql)
    env = str(environment or "dev").casefold()
    if env not in {"dev", "staging", "prod"}:
        raise ValueError("environment must be dev, staging, or prod")

    fingerprint = _fingerprint(sql, env, descriptor)
    blocked = False
    block_reason: str | None = None
    if descriptor.destructive and env == "prod":
        if os.getenv("ADE_PROD_DESTRUCTIVE_BREAK_GLASS", "false").casefold() != "true":
            blocked = True
            block_reason = "production destructive operations are blocked unless break-glass policy is explicitly enabled"

    controls = [
        "ToolRegistry execution path",
        "builder/admin actor mode",
        "explicit approval",
        "approval fingerprint must match the exact statement",
        "post-execution verification",
    ]
    if descriptor.destructive:
        controls.extend(
            [
                "explicit destructive confirmation",
                "blast-radius review",
                "recovery assessment",
            ]
        )
    if env == "prod":
        controls.append("production change approval")

    return {
        "status": "BLOCKED_POLICY" if blocked else "PASS",
        "mode": "PLAN_ONLY",
        "environment": env,
        "statement_type": descriptor.statement_type,
        "object_type": descriptor.object_type,
        "target": descriptor.target,
        "risk_level": descriptor.risk_level,
        "destructive": descriptor.destructive,
        "statement_preview": _redact(_normalize(sql)),
        "approval_fingerprint": fingerprint,
        "approval_required": True,
        "destructive_confirmation_required": descriptor.destructive,
        "blocked": blocked,
        "block_reason": block_reason,
        "required_controls": controls,
        "verification_plan": _verification_plan(descriptor, sql),
        "blast_radius_review_required": descriptor.destructive or descriptor.statement_type in {"ALTER", "CREATE_OR_REPLACE", "GRANT", "REVOKE"},
        "dependency_analysis_required": descriptor.destructive or descriptor.statement_type in {"ALTER", "CREATE_OR_REPLACE"},
        "rollback_guidance": (
            "Use Snowflake Time Travel/UNDROP or a tested replacement strategy where supported; "
            "validate dependencies before destructive execution."
            if descriptor.destructive
            else "Record the pre-change definition and use an inverse migration when rollback is required."
        ),
    }


class GovernedSnowflakeMutationExecutor:
    """Execute a previously planned Snowflake statement behind deterministic controls."""

    def __init__(self, connector: SnowflakeConnector) -> None:
        if not isinstance(connector, SnowflakeConnector):
            raise TypeError("GovernedSnowflakeMutationExecutor requires SnowflakeConnector")
        self.connector = connector

    def plan(self, sql: str, *, environment: str = "dev") -> dict[str, Any]:
        return plan_snowflake_mutation(sql, environment=environment)

    def execute(
        self,
        sql: str,
        *,
        environment: str = "dev",
        approval_fingerprint: str,
        approved: bool = False,
        confirm_destructive: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan(sql, environment=environment)
        if plan["status"] == "BLOCKED_POLICY":
            return plan
        if plan["status"] != "PASS":
            return plan
        if not approved:
            return {
                **plan,
                "status": "BLOCKED_APPROVAL",
                "reason": "explicit ToolRegistry approval is required",
            }
        if approval_fingerprint != plan["approval_fingerprint"]:
            return {
                **plan,
                "status": "BLOCKED_APPROVAL",
                "code": "APPROVAL_FINGERPRINT_MISMATCH",
                "reason": "approval does not match the exact SQL/environment/target being executed",
            }
        if plan["destructive"] and not confirm_destructive:
            return {
                **plan,
                "status": "BLOCKED_APPROVAL",
                "code": "DESTRUCTIVE_CONFIRMATION_REQUIRED",
                "reason": "destructive execution requires an additional explicit confirmation",
            }
        if dry_run:
            return {
                **plan,
                "status": "PASS",
                "mode": "DRY_RUN",
                "executed": False,
            }

        before: list[dict[str, Any]] = []
        verification_plan = list(plan["verification_plan"])
        if verification_plan and verification_plan[0].get("kind") == "object_presence":
            try:
                before = list(self.connector._read(verification_plan[0]["sql"]).rows)
            except Exception:
                before = []

        result = self.connector.execute_governed_mutation(sql)

        verification: list[dict[str, Any]] = []
        for item in verification_plan:
            try:
                rows = list(self.connector._read(item["sql"]).rows)
                passed = True
                if item["kind"] == "object_presence":
                    passed = bool(rows) is bool(item["expect_present"])
                elif item["kind"] == "column_presence":
                    expected = str(item.get("column") or "").casefold()
                    present = any(
                        str(row.get("name") or row.get("NAME") or "").casefold() == expected
                        for row in rows
                    )
                    passed = present is bool(item["expect_present"])
                elif item["kind"] == "row_count":
                    row_count = int((rows[0].get("ROW_COUNT") or rows[0].get("row_count") or 0)) if rows else -1
                    passed = row_count == int(item["expected"])
                elif item["kind"] == "query_status":
                    mutation_query_id = result.query_id
                    if mutation_query_id:
                        matching = [
                            row
                            for row in rows
                            if str(row.get("QUERY_ID") or row.get("query_id") or "") == str(mutation_query_id)
                        ]
                        if matching:
                            status = str(
                                matching[0].get("EXECUTION_STATUS")
                                or matching[0].get("execution_status")
                                or ""
                            ).upper()
                            passed = status in {"SUCCESS", ""}
                verification.append(
                    {
                        "kind": item["kind"],
                        "passed": passed,
                        "row_count": len(rows),
                        "evidence": rows[:20],
                    }
                )
            except Exception as exc:
                verification.append(
                    {
                        "kind": item["kind"],
                        "passed": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        verified = all(item["passed"] for item in verification) if verification else bool(
            result.query_id or result.metadata.get("statement_executed")
        )
        return {
            "status": "PASS" if verified else "FAIL",
            "mode": "EXECUTED_AND_VERIFIED",
            "environment": plan["environment"],
            "statement_type": plan["statement_type"],
            "object_type": plan["object_type"],
            "target": plan["target"],
            "risk_level": plan["risk_level"],
            "destructive": plan["destructive"],
            "approval_fingerprint": plan["approval_fingerprint"],
            "statement_preview": plan["statement_preview"],
            "executed": True,
            "query_id": result.query_id,
            "before_state_count": len(before),
            "verification": verification,
            "verified": verified,
        }
