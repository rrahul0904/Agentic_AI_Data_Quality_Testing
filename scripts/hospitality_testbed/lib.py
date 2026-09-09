"""Shared configuration, evidence, safety, and connection helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

PASS = "PASS"
FAIL = "FAIL"
SKIP_EXTERNAL = "SKIP_EXTERNAL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
BLOCKED_APPROVAL = "BLOCKED_APPROVAL"
NOT_RUN = "NOT_RUN"
VALID_STATUSES = {PASS, FAIL, SKIP_EXTERNAL, BLOCKED_EXTERNAL, BLOCKED_APPROVAL, NOT_RUN}

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DEFAULT_ARTIFACT_DIR = ROOT / "artifacts" / "hospitality"
DEFAULT_STATE_DIR = ROOT / ".ade" / "testbed"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
SUSPICIOUS_DATABASE_MARKERS = ("PROD", "PRODUCTION", "PRD")


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Configuration must be a mapping: {path}")
    return value


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in {None, ""} else default


def approved() -> bool:
    return str(env("ADE_TESTBED_MUTATION_APPROVED", "false")).lower() == "true"


def validate_identifier(value: str, label: str = "identifier") -> str:
    if not IDENTIFIER.fullmatch(str(value or "")):
        raise ValueError(f"Unsafe Snowflake {label}: {value!r}")
    return value.upper()


def testbed_database(*, destructive: bool = False, mutation: bool = False) -> str:
    configured = env("ADE_SNOWFLAKE_DATABASE", "HOSPITALITY_TESTBED") or ""
    database = validate_identifier(configured, "database")
    if (destructive or mutation) and any(marker in database for marker in SUSPICIOUS_DATABASE_MARKERS):
        raise ValueError(f"Refusing testbed mutation against production-looking database {database!r}")
    if (destructive or mutation) and database == "HOSPITALITY_DW":
        raise ValueError("Refusing testbed mutation against the shared HOSPITALITY_DW proving-ground database")
    return database


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_stage_path(item: dict[str, Any], generation_id: str) -> str:
    """Return a pipe-compatible, generation-isolated object path."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", generation_id):
        raise ValueError(f"Unsafe generation ID: {generation_id!r}")
    source = PurePosixPath(str(item["file"]))
    if source.is_absolute() or len(source.parts) < 3 or ".." in source.parts:
        raise ValueError(f"Unsafe manifest file path: {source!s}")
    family, entity, *partition_and_file = source.parts
    return str(PurePosixPath(family, entity, f"generation_id={generation_id}", *partition_and_file))


def redact(value: Any) -> Any:
    secret_keys = ("password", "secret", "token", "private_key", "aws_key", "credential")
    if isinstance(value, dict):
        return {key: ("***REDACTED***" if any(item in key.lower() for item in secret_keys) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def evidence_path(name: str) -> Path:
    root = Path(env("ADE_TESTBED_ARTIFACT_DIR", str(DEFAULT_ARTIFACT_DIR)) or str(DEFAULT_ARTIFACT_DIR))
    return root / name


def state_path(name: str = "state.json") -> Path:
    root = Path(env("ADE_TESTBED_STATE_DIR", str(DEFAULT_STATE_DIR)) or str(DEFAULT_STATE_DIR))
    return root / name


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def update_state(**changes: Any) -> dict[str, Any]:
    path = state_path()
    current: dict[str, Any] = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(changes)
    write_json(path, current)
    return current


def snowflake_env_missing() -> list[str]:
    required = ["ADE_SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER", "ADE_SNOWFLAKE_PASSWORD"]
    return [name for name in required if not env(name)]


def aws_env_missing() -> list[str]:
    required = ["ADE_TESTBED_S3_BUCKET", "AWS_REGION"]
    return [name for name in required if not env(name)]


def snowflake_connect(*, include_database: bool = True, include_warehouse: bool = True, role: str | None = None):
    missing = snowflake_env_missing()
    if missing:
        raise RuntimeError(f"{BLOCKED_EXTERNAL}: missing {', '.join(missing)}")
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError(f"{BLOCKED_EXTERNAL}: snowflake-connector-python is not installed") from exc
    kwargs = dict(
        account=env("ADE_SNOWFLAKE_ACCOUNT"),
        user=env("ADE_SNOWFLAKE_USER"),
        password=env("ADE_SNOWFLAKE_PASSWORD"),
        role=role or env("ADE_SNOWFLAKE_ROLE", "ADE_HOSPITALITY_TESTBED_ROLE"),
        session_parameters={"QUERY_TAG": "ADE_HOSPITALITY_TESTBED"},
    )
    if include_database:
        kwargs.update(database=testbed_database(), schema=env("ADE_SNOWFLAKE_SCHEMA", "RAW"))
    if include_warehouse:
        kwargs["warehouse"] = env("ADE_SNOWFLAKE_WAREHOUSE", "ADE_HOSPITALITY_TESTBED_WH")
    return snowflake.connector.connect(**kwargs)


def render_sql(text: str) -> str:
    database = testbed_database()
    replacements = {
        "{{DATABASE}}": database,
        "{{WAREHOUSE}}": validate_identifier(env("ADE_SNOWFLAKE_WAREHOUSE", "ADE_HOSPITALITY_TESTBED_WH") or "", "warehouse"),
        "{{ROLE}}": validate_identifier(env("ADE_SNOWFLAKE_ROLE", "ADE_HOSPITALITY_TESTBED_ROLE") or "", "role"),
        "{{S3_BUCKET}}": env("ADE_TESTBED_S3_BUCKET", "REPLACE_ME_HOSPITALITY_BUCKET") or "",
        "{{S3_PREFIX}}": (env("ADE_TESTBED_S3_PREFIX", "hospitality") or "hospitality").strip("/"),
        "{{STORAGE_INTEGRATION}}": validate_identifier(env("ADE_TESTBED_STORAGE_INTEGRATION", "ADE_HOSPITALITY_S3_INT") or "", "integration"),
        "{{AWS_ROLE_ARN}}": env("ADE_TESTBED_AWS_ROLE_ARN", "arn:aws:iam::000000000000:role/REPLACE_ME_SNOWFLAKE") or "",
        "{{SNS_TOPIC_ARN}}": env("ADE_TESTBED_SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:REPLACE_ME_HOSPITALITY") or "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def split_sql(text: str) -> list[str]:
    """Split Snowflake SQL on unquoted semicolons while preserving comments and literals."""
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            current.append(character)
            if character == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            current.append(character)
            if character == "*" and following == "/":
                current.append(following)
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            current.append(character)
            if character == quote:
                if following == quote:
                    current.append(following)
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character == "-" and following == "-":
            current.extend((character, following))
            line_comment = True
            index += 2
            continue
        if character == "/" and following == "*":
            current.extend((character, following))
            block_comment = True
            index += 2
            continue
        if character in {"'", '"'}:
            quote = character
            current.append(character)
        elif character == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(character)
        index += 1
    if quote or block_comment:
        raise ValueError("Unterminated SQL string or block comment")
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def emit(payload: dict[str, Any], *, output: Path | None = None) -> int:
    if output:
        write_json(output, payload)
    print(json.dumps(redact(payload), indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") in {PASS, SKIP_EXTERNAL, BLOCKED_EXTERNAL, BLOCKED_APPROVAL, NOT_RUN} else 1
