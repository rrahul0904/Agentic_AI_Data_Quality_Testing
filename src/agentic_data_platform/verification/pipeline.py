from __future__ import annotations
from collections.abc import Callable
from agentic_data_platform.models import VerificationFinding, VerificationReport
from agentic_data_platform.verification.checks import parse_check, static_safety_check
from agentic_data_platform.verification.engine import VerificationEngine, VerificationGate

OptionalCheck = Callable[[], VerificationFinding]

def build_standard_pipeline(sql: str, *, schema_contract: OptionalCheck, target_dry_run: OptionalCheck, unit_tests: OptionalCheck, data_quality: OptionalCheck, schema_parity: OptionalCheck, row_count_parity: OptionalCheck, hash_or_sample_parity: OptionalCheck, policy_approval: OptionalCheck) -> list[VerificationGate]:
    return [VerificationGate("static_safety",lambda: static_safety_check(sql)),VerificationGate("parse_compile",lambda: parse_check(sql)),VerificationGate("schema_contract",schema_contract),VerificationGate("target_dry_run",target_dry_run),VerificationGate("unit_tests",unit_tests),VerificationGate("data_quality",data_quality),VerificationGate("schema_parity",schema_parity),VerificationGate("row_count_parity",row_count_parity),VerificationGate("hash_or_sample_parity",hash_or_sample_parity,blocking=False),VerificationGate("policy_approval",policy_approval)]

def verify_standard(sql: str, **checks: OptionalCheck) -> VerificationReport:
    return VerificationEngine().run_ordered(build_standard_pipeline(sql, **checks))
