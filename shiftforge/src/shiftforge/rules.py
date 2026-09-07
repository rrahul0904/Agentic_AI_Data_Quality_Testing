from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from .models import RuleHit, Severity


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    apply: Callable[[str], tuple[str, list[RuleHit]]]


def _sub_rule(rule_id: str, message: str, pattern: str, replacement: str, sql: str,
              flags: int = re.IGNORECASE) -> tuple[str, list[RuleHit]]:
    hits: list[RuleHit] = []
    rx = re.compile(pattern, flags)

    def repl(match: re.Match[str]) -> str:
        before = match.group(0)
        after = match.expand(replacement)
        hits.append(RuleHit(rule_id=rule_id, message=message, severity=Severity.info,
                            before=before, after=after, auto_fixed=True))
        return after

    return rx.sub(repl, sql), hits


def backticks(sql: str):
    return _sub_rule(
        "BQ001", "Converted BigQuery backtick identifiers to Redshift-compatible identifiers.",
        r"`([^`]+)`", r"\1", sql,
    )


def safe_cast(sql: str):
    return _sub_rule(
        "BQ002", "SAFE_CAST is not portable to Redshift; replaced with CAST and flagged semantic risk.",
        r"SAFE_CAST\s*\((.*?)\s+AS\s+([A-Za-z0-9_(), ]+)\)", r"CAST(\1 AS \2)", sql,
        flags=re.IGNORECASE | re.DOTALL,
    )


def countif(sql: str):
    pattern = re.compile(r"COUNTIF\s*\((.*?)\)", re.IGNORECASE | re.DOTALL)
    hits: list[RuleHit] = []
    def repl(m: re.Match[str]) -> str:
        before = m.group(0)
        after = f"SUM(CASE WHEN {m.group(1)} THEN 1 ELSE 0 END)"
        hits.append(RuleHit(rule_id="BQ003", message="Converted COUNTIF to conditional SUM.",
                            before=before, after=after, auto_fixed=True))
        return after
    return pattern.sub(repl, sql), hits


def ifnull(sql: str):
    return _sub_rule("BQ004", "Normalized IFNULL to COALESCE.", r"\bIFNULL\s*\(", "COALESCE(", sql)


def string_agg(sql: str):
    # Redshift LISTAGG syntax differs materially for ORDER BY clauses. Handle only the safe 2-arg form.
    pattern = re.compile(r"STRING_AGG\s*\(([^,()]+),\s*([^()]+?)\)", re.IGNORECASE)
    hits: list[RuleHit] = []
    def repl(m: re.Match[str]) -> str:
        before = m.group(0)
        after = f"LISTAGG({m.group(1).strip()}, {m.group(2).strip()})"
        hits.append(RuleHit(rule_id="BQ005", message="Converted simple STRING_AGG to LISTAGG.",
                            before=before, after=after, auto_fixed=True))
        return after
    return pattern.sub(repl, sql), hits


def date_add(sql: str):
    # DATE_ADD(date_expr, INTERVAL N DAY) -> DATEADD(day, N, date_expr)
    pattern = re.compile(
        r"DATE_ADD\s*\(\s*(.+?)\s*,\s*INTERVAL\s+([+-]?\d+)\s+(DAY|WEEK|MONTH|YEAR)\s*\)",
        re.IGNORECASE,
    )
    hits: list[RuleHit] = []
    def repl(m: re.Match[str]) -> str:
        before = m.group(0)
        after = f"DATEADD({m.group(3).lower()}, {m.group(2)}, {m.group(1).strip()})"
        hits.append(RuleHit(rule_id="BQ006", message="Converted BigQuery DATE_ADD to Redshift DATEADD.",
                            before=before, after=after, auto_fixed=True))
        return after
    return pattern.sub(repl, sql), hits


def regexp_contains(sql: str):
    pattern = re.compile(r"REGEXP_CONTAINS\s*\(([^,]+),\s*([^\)]+)\)", re.IGNORECASE)
    hits: list[RuleHit] = []
    def repl(m: re.Match[str]) -> str:
        before = m.group(0)
        after = f"REGEXP_INSTR({m.group(1).strip()}, {m.group(2).strip()}) > 0"
        hits.append(RuleHit(rule_id="BQ007", message="Converted REGEXP_CONTAINS to REGEXP_INSTR predicate.",
                            before=before, after=after, auto_fixed=True))
        return after
    return pattern.sub(repl, sql), hits


def detect_high_risk(sql: str) -> list[RuleHit]:
    checks = [
        ("RISK_UNNEST", r"\bUNNEST\s*\(", "UNNEST/array semantics require model-specific review."),
        ("RISK_STRUCT", r"\bSTRUCT\s*\(|\bARRAY\s*<", "STRUCT/ARRAY types require Redshift SUPER or relational flattening."),
        ("RISK_JSON", r"\bJSON_(EXTRACT|VALUE|QUERY|EXTRACT_SCALAR)\b", "BigQuery JSON functions require explicit Redshift SUPER/JSON mapping."),
        ("RISK_STAR_EXCEPT", r"SELECT\s+\*\s+EXCEPT\s*\(", "SELECT * EXCEPT is BigQuery-specific and needs explicit column expansion."),
        ("RISK_GEOGRAPHY", r"\b(ST_GEOG|GEOGRAPHY|ST_DISTANCE)\b", "Geospatial behavior needs a dedicated compatibility pass."),
    ]
    hits: list[RuleHit] = []
    for rule_id, pattern, message in checks:
        if re.search(pattern, sql, re.IGNORECASE):
            hits.append(RuleHit(rule_id=rule_id, message=message, severity=Severity.warning, auto_fixed=False))
    return hits


RULES = [backticks, safe_cast, countif, ifnull, string_agg, date_add, regexp_contains]


def apply_rules(sql: str) -> tuple[str, list[RuleHit]]:
    current = sql
    hits: list[RuleHit] = []
    for fn in RULES:
        current, new_hits = fn(current)
        hits.extend(new_hits)
    hits.extend(detect_high_risk(current))
    return current, hits
