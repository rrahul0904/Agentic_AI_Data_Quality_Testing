#!/usr/bin/env python3
"""Final deterministic release audit for secrets and user-facing product debt."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".parquet", ".avro", ".db", ".sqlite", ".sqlite3", ".woff", ".woff2",
}
SKIP_PREFIXES = (
    "node_modules/", ".next/", ".git/", ".venv/", "dist/", "build/",
    "hospitality-snowflake-data-platform/dbt/target/",
)
PRODUCTION_PREFIXES = (
    "src/", "apps/", "scripts/", ".github/", "shiftforge/src/", "local-data-harness/",
)
SECURITY_FIXTURE_PATHS = {
    "tests/test_final_acceptance_audit.py",
}
USER_FACING_PREFIXES = (
    "apps/web/", "src/agentic_data_platform/api/", "README.md", "docs/",
)
BLOCKING_PRODUCT_PHRASES = (
    "coming soon",
    "next wave",
    "partial / next wave",
    "roadmap placeholder",
    "mock later",
    "not implemented for users",
)
DEBT_MARKERS = ("TODO", "FIXME", "HACK", "NotImplemented", "stub", "temporary", "fake", "roadmap")

HIGH_SIGNAL_SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "credential_url": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"),
}
LITERAL_SECRET = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|apikey|private[_-]?key|aws[_-]?secret)"
    r"\s*[:=]\s*['\"]([^'\"\n]{8,})['\"]"
)
SAFE_LITERAL_HINTS = (
    "example", "fixture", "dummy", "fake", "test", "changeme", "placeholder",
    "redacted", "super-secret-value", "not-a-real", "local-dev",
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [
        ROOT / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    ]


def readable(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return (
        path.is_file()
        and path.suffix.casefold() not in BINARY_SUFFIXES
        and not any(rel.startswith(prefix) for prefix in SKIP_PREFIXES)
        and path.name not in {"package-lock.json"}
    )


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def security_audit(files: list[Path]) -> tuple[list[dict[str, object]], int]:
    findings: list[dict[str, object]] = []
    scanned = 0
    for path in files:
        if not readable(path):
            continue
        text = read_text(path)
        if not text:
            continue
        scanned += 1
        rel = path.relative_to(ROOT).as_posix()
        if rel not in SECURITY_FIXTURE_PATHS:
            for rule_id, pattern in HIGH_SIGNAL_SECRET_PATTERNS.items():
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append({"rule_id": rule_id, "file": rel, "line": line})
        if rel.startswith(PRODUCTION_PREFIXES):
            for match in LITERAL_SECRET.finditer(text):
                value = match.group(2).casefold()
                if any(hint in value for hint in SAFE_LITERAL_HINTS):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                findings.append({
                    "rule_id": "literal_secret_assignment",
                    "file": rel,
                    "line": line,
                    "name": match.group(1),
                })
    return findings, scanned


def product_debt_audit(files: list[Path]) -> tuple[list[dict[str, object]], dict[str, int]]:
    blocking: list[dict[str, object]] = []
    marker_counts = {marker: 0 for marker in DEBT_MARKERS}
    for path in files:
        if not readable(path):
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = read_text(path)
        if not text:
            continue
        for marker in DEBT_MARKERS:
            marker_counts[marker] += text.count(marker)
        if not rel.startswith(USER_FACING_PREFIXES):
            continue
        lowered = text.casefold()
        for phrase in BLOCKING_PRODUCT_PHRASES:
            offset = lowered.find(phrase)
            if offset >= 0:
                blocking.append({
                    "phrase": phrase,
                    "file": rel,
                    "line": text.count("\n", 0, offset) + 1,
                })
    return blocking, marker_counts


def main() -> int:
    files = tracked_files()
    security, scanned = security_audit(files)
    blocking_debt, marker_counts = product_debt_audit(files)
    report = {
        "status": "PASS" if not security and not blocking_debt else "FAIL",
        "tracked_files": len(files),
        "text_files_scanned": scanned,
        "security_findings": security,
        "blocking_product_debt": blocking_debt,
        "repository_debt_marker_counts": marker_counts,
        "policy": {
            "security": "Fails on high-confidence credential material and production literal secret assignments.",
            "product_debt": "Fails only on user-facing release-placeholder phrases; generic debt markers are counted for classification.",
        },
    }
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
