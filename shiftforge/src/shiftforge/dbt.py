from __future__ import annotations

import re
from pathlib import Path
from .models import RuleHit, Severity

CONFIG_RE = re.compile(r"\{\{\s*config\s*\((.*?)\)\s*\}\}", re.IGNORECASE | re.DOTALL)
SORT_RE = re.compile(r"\b(?:sort|sortkey|sort_key)\s*=\s*(?:\[([^\]]+)\]|['\"]([^'\"]+)['\"])", re.IGNORECASE)
ALIAS_RE = re.compile(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)
BARE_SELECT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\.]*$")


def extract_sort_keys(sql: str) -> list[str]:
    config = CONFIG_RE.search(sql)
    if not config:
        return []
    keys: list[str] = []
    for m in SORT_RE.finditer(config.group(1)):
        if m.group(1):
            parts = [p.strip().strip("'\"") for p in m.group(1).split(',')]
            keys.extend([p for p in parts if p])
        elif m.group(2):
            keys.append(m.group(2).strip())
    return list(dict.fromkeys(keys))


def _top_level_select_body(sql: str) -> str | None:
    # Lightweight parser: isolate the last top-level SELECT list before FROM. Good enough for dbt MVP;
    # complex nested queries are flagged by validation rather than silently guessed.
    masked = CONFIG_RE.sub("", sql)
    depth = 0
    select_pos = None
    i = 0
    upper = masked.upper()
    while i < len(masked):
        ch = masked[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif depth == 0 and upper.startswith("SELECT", i):
            select_pos = i + 6
            i += 5
        elif depth == 0 and select_pos is not None and upper.startswith("FROM", i):
            return masked[select_pos:i]
        i += 1
    return None


def _split_top_level_csv(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote and (i == 0 or text[i-1] != '\\'):
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif ch == ',' and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def selected_columns(sql: str) -> list[str]:
    body = _top_level_select_body(sql)
    if not body:
        return []
    cols: list[str] = []
    for expr in _split_top_level_csv(body):
        alias = ALIAS_RE.search(expr)
        if alias:
            cols.append(alias.group(1))
            continue
        cleaned = re.sub(r"--.*$", "", expr, flags=re.MULTILINE).strip()
        if BARE_SELECT_RE.match(cleaned):
            cols.append(cleaned.split('.')[-1])
    return list(dict.fromkeys(cols))


def enforce_sort_keys(sql: str, hints: dict[str, str] | None = None) -> tuple[str, list[RuleHit], list[str]]:
    hints = hints or {}
    sort_keys = extract_sort_keys(sql)
    selected = set(c.lower() for c in selected_columns(sql))
    missing = [k for k in sort_keys if k.lower() not in selected]
    hits: list[RuleHit] = []
    unresolved: list[str] = []
    current = sql
    for key in missing:
        expr = hints.get(key)
        if expr:
            body = _top_level_select_body(current)
            if body is None:
                unresolved.append(key)
                continue
            # Insert just before the top-level FROM by locating this exact select body.
            select_start = current.find(body)
            insert_at = select_start + len(body)
            sep = ",\n    " if body.strip() else ""
            current = current[:insert_at] + sep + f"{expr} AS {key}\n" + current[insert_at:]
            hits.append(RuleHit(
                rule_id="RS_SORTKEY_001",
                message=f"Added missing Redshift sort key '{key}' to the SELECT list using an explicit hint.",
                severity=Severity.info,
                before=None,
                after=f"{expr} AS {key}",
                auto_fixed=True,
            ))
            selected.add(key.lower())
        else:
            unresolved.append(key)
            hits.append(RuleHit(
                rule_id="RS_SORTKEY_002",
                message=f"Sort key '{key}' is not produced by the model. Provide a source expression hint or resolve manually.",
                severity=Severity.error,
                auto_fixed=False,
            ))
    return current, hits, unresolved


def discover_models(project_root: Path) -> list[Path]:
    models_dir = project_root / "models"
    if not models_dir.exists():
        return []
    return sorted(
        p for p in models_dir.rglob("*.sql")
        if "converted" not in p.parts and "target" not in p.parts
    )
