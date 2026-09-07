from __future__ import annotations

import re
from dataclasses import dataclass

_FORBIDDEN = (re.compile(r"\bDROP\s+(?:DATABASE|SCHEMA)\b", re.I), re.compile(r"\bTRUNCATE\b", re.I), re.compile(r"\bALTER\s+SYSTEM\b", re.I), re.compile(r"\bGRANT\s+OWNERSHIP\b", re.I))

@dataclass(frozen=True)
class ColumnDefinition:
    name: str
    data_type: str
    nullable: bool = True

@dataclass(frozen=True)
class DDLObject:
    object_type: str
    name: str
    columns: tuple[ColumnDefinition, ...] = ()

@dataclass(frozen=True)
class SQLAnalysis:
    dialect: str
    normalized_sql: str
    safe: bool
    parseable: bool
    forbidden_statements: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    objects: tuple[DDLObject, ...] = ()
    errors: tuple[str, ...] = ()

def strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)

def normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", strip_comments(sql)).strip()

def identify_dialect(sql: str) -> str:
    cleaned = strip_comments(sql)
    if re.search(r"\[[^\]]+\]|\bNVARCHAR\b|\bDATETIME2\b|\bIDENTITY\s*\(", cleaned, re.I): return "sqlserver"
    if re.search(r"\bVARIANT\b|\bTIMESTAMP_NTZ\b|\bQUALIFY\b", cleaned, re.I): return "snowflake"
    if re.search(r"`[^`]+`|\bSTRUCT\s*<|\bUNNEST\s*\(", cleaned, re.I): return "bigquery"
    if re.search(r"\bUSING\s+DELTA\b|\bOPTIMIZE\b|\bVACUUM\b", cleaned, re.I): return "databricks"
    return "ansi"

def forbidden_statements(sql: str) -> tuple[str, ...]:
    normalized = normalize_sql(sql)
    return tuple(match.group(0).upper() for pattern in _FORBIDDEN if (match := pattern.search(normalized)))

def _balanced(sql: str) -> bool:
    depth = 0; quote: str | None = None; i = 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote: i += 2; continue
                quote = None
        else:
            if ch in {"'", '"'}: quote = ch
            elif ch == "(": depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0: return False
        i += 1
    return depth == 0 and quote is None

def extract_dependencies(sql: str) -> tuple[str, ...]:
    refs = re.findall(r"\b(?:FROM|JOIN|REFERENCES)\s+([\[\]`\"\w.$-]+)", strip_comments(sql), flags=re.I)
    normalized = [ref.replace("[", "").replace("]", "").replace("`", "").replace('"', "") for ref in refs]
    return tuple(dict.fromkeys(normalized))

def _split_columns(body: str) -> list[str]:
    parts=[]; current=[]; depth=0; quote=None
    for ch in body:
        if quote:
            current.append(ch)
            if ch == quote: quote=None
        elif ch in {"'", '"'}: quote=ch; current.append(ch)
        elif ch == "(": depth += 1; current.append(ch)
        elif ch == ")": depth -= 1; current.append(ch)
        elif ch == "," and depth == 0: parts.append("".join(current).strip()); current=[]
        else: current.append(ch)
    if current: parts.append("".join(current).strip())
    return parts

def extract_ddl_objects(sql: str) -> tuple[DDLObject, ...]:
    match = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+([\[\]`\"\w.$-]+)\s*\((.*)\)\s*;?\s*$", re.I|re.S).search(strip_comments(sql).strip())
    if not match: return ()
    raw_name, body = match.groups(); name = raw_name.replace("[","").replace("]","").replace("`","").replace('"',"")
    columns=[]
    for item in _split_columns(body):
        if re.match(r"^(?:CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\b", item, re.I): continue
        col_match = re.match(r"[\[`\"]?([\w$-]+)[\]`\"]?\s+(.+)$", item, re.S)
        if not col_match: continue
        col_name, remainder = col_match.groups()
        type_text = re.split(r"\s+(?=NOT\s+NULL\b|NULL\b|PRIMARY\s+KEY\b|DEFAULT\b|IDENTITY\b|CONSTRAINT\b|REFERENCES\b|UNIQUE\b|CHECK\b)", remainder.strip(), maxsplit=1, flags=re.I)[0].strip()
        if not type_text: continue
        columns.append(ColumnDefinition(col_name, re.sub(r"\s+", " ", type_text).upper(), not bool(re.search(r"\bNOT\s+NULL\b", remainder, re.I))))
    return (DDLObject("table", name, tuple(columns)),)

def analyze_sql(sql: str, dialect: str | None = None) -> SQLAnalysis:
    normalized = normalize_sql(sql); errors=[]
    if not normalized: errors.append("SQL is empty")
    if not _balanced(sql): errors.append("unbalanced parentheses or quotes")
    if not re.match(r"^(SELECT|WITH|CREATE|ALTER|INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE)\b", normalized, re.I): errors.append("unsupported or unrecognized SQL statement")
    forbidden = forbidden_statements(sql); objects = extract_ddl_objects(sql)
    if re.match(r"^CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\b", normalized, re.I) and not objects: errors.append("CREATE TABLE could not be parsed")
    return SQLAnalysis(dialect or identify_dialect(sql), normalized, not forbidden, not errors, forbidden, extract_dependencies(sql), objects, tuple(errors))
