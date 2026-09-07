from __future__ import annotations
from dataclasses import dataclass
from agentic_data_platform.models import VerificationFinding
from agentic_data_platform.sql.engine import analyze_sql

@dataclass(frozen=True)
class DataSnapshot:
    schema: dict[str,str]
    row_count: int
    hash_value: str | None = None
    quality_failures: tuple[str,...] = ()

def static_safety_check(sql: str) -> VerificationFinding:
    a=analyze_sql(sql); return VerificationFinding("static_safety",a.safe,detail=", ".join(a.forbidden_statements) if not a.safe else "no forbidden statements",evidence={"forbidden":list(a.forbidden_statements)})
def parse_check(sql: str) -> VerificationFinding:
    a=analyze_sql(sql); return VerificationFinding("parse_compile",a.parseable,detail="; ".join(a.errors) or "parseable")
def schema_parity_check(source: DataSnapshot,target: DataSnapshot) -> VerificationFinding:
    passed=source.schema==target.schema; return VerificationFinding("schema_parity",passed,detail="schemas match" if passed else "schema mismatch",evidence={"source":source.schema,"target":target.schema})
def row_count_parity_check(source: DataSnapshot,target: DataSnapshot) -> VerificationFinding:
    passed=source.row_count==target.row_count; return VerificationFinding("row_count_parity",passed,detail=f"source={source.row_count}, target={target.row_count}")
def hash_parity_check(source: DataSnapshot,target: DataSnapshot,*,required: bool=False) -> VerificationFinding:
    if source.hash_value is None or target.hash_value is None: return VerificationFinding("hash_parity",not required,severity="error" if required else "warning",detail="hash evidence unavailable",blocking=required)
    return VerificationFinding("hash_parity",source.hash_value==target.hash_value,detail="hashes match" if source.hash_value==target.hash_value else "hash mismatch")
def data_quality_check(target: DataSnapshot) -> VerificationFinding:
    passed=not target.quality_failures; return VerificationFinding("data_quality",passed,detail="; ".join(target.quality_failures) or "quality rules passed")
def synthetic_reconciliation(source: DataSnapshot,target: DataSnapshot) -> list[VerificationFinding]:
    return [schema_parity_check(source,target),row_count_parity_check(source,target),hash_parity_check(source,target),data_quality_check(target)]
