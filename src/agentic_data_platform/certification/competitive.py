"""Exact-head competitive capability ledger with explicit local/external boundaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Mapping


_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


class CompetitiveStatus(str, Enum):
    IMPLEMENTED_UNCERTIFIED = "IMPLEMENTED_UNCERTIFIED"
    CERTIFIED_LOCAL = "CERTIFIED_LOCAL"
    NOT_RUN_EXTERNAL = "NOT_RUN_EXTERNAL"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"


@dataclass(frozen=True)
class CapabilityRecord:
    capability: str
    scope: str
    status: CompetitiveStatus
    evidence: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


_LOCAL_GATE_CAPABILITIES = (
    ("ade_search_persistent_hybrid", "search"),
    ("ade_search_multi_index_scoring", "search"),
    ("ade_search_local_lsh_candidates", "search"),
    ("document_native_extraction", "document"),
    ("document_page_asset_provenance", "document"),
    ("document_structured_field_evidence", "document"),
    ("document_search_incremental_sync", "document"),
    ("embedded_agent_sdk", "agent"),
    ("acp_protocol_adapter", "agent"),
    ("acp_fingerprint_permission_bridge", "agent"),
    ("ssh_remote_workspace_governance", "workspace"),
    ("portable_compute_planning", "compute"),
    ("sql_antipattern_regression_1077", "sql"),
    ("column_lineage_regression_500", "lineage"),
    ("native_desktop_linux_macos_windows", "desktop"),
)

_EXTERNAL_CAPABILITIES = (
    ("snowflake_cortex_search_live", "search", CompetitiveStatus.NOT_RUN_EXTERNAL),
    ("snowflake_spcs_gpu_live", "compute", CompetitiveStatus.NOT_RUN_EXTERNAL),
    ("snowflake_ai_parse_document_live", "document", CompetitiveStatus.NOT_RUN_EXTERNAL),
    ("external_learned_embedding_provider", "search", CompetitiveStatus.NOT_RUN_EXTERNAL),
    ("external_learned_reranker_provider", "search", CompetitiveStatus.NOT_RUN_EXTERNAL),
    ("external_llm_provider_execution", "agent", CompetitiveStatus.NOT_RUN_EXTERNAL),
    ("ade_bench_upstream_native_ade_driver", "benchmark", CompetitiveStatus.BLOCKED_EXTERNAL),
    ("cross_product_superiority_benchmark", "benchmark", CompetitiveStatus.NOT_RUN_EXTERNAL),
)


def build_competitive_ledger(
    commit_sha: str,
    *,
    local_gate_passed: bool = False,
    workflow: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sha = str(commit_sha).strip()
    if not _SHA.fullmatch(sha):
        raise ValueError("commit_sha must be an exact 40-character Git SHA")
    local_status = (
        CompetitiveStatus.CERTIFIED_LOCAL
        if local_gate_passed
        else CompetitiveStatus.IMPLEMENTED_UNCERTIFIED
    )
    workflow_evidence = dict(workflow or {})
    local = [
        CapabilityRecord(
            capability=name,
            scope=scope,
            status=local_status,
            evidence={
                "commit_sha": sha,
                "local_gate_passed": bool(local_gate_passed),
                **workflow_evidence,
            },
        ).as_dict()
        for name, scope in _LOCAL_GATE_CAPABILITIES
    ]
    independent = [
        CapabilityRecord(
            capability="coco_local_parity_regression",
            scope="platform",
            status=CompetitiveStatus.IMPLEMENTED_UNCERTIFIED,
            evidence={
                "commit_sha": sha,
                "reason": "owned by the independent exact-head ade-capability-superiority workflow; not inferred from this gate",
            },
        ).as_dict()
    ]
    external = [
        CapabilityRecord(
            capability=name,
            scope=scope,
            status=status,
            evidence={
                "commit_sha": sha,
                "reason": (
                    "current upstream dbt-labs/ade-bench does not expose ADE as a native agent driver"
                    if name == "ade_bench_upstream_native_ade_driver"
                    else "requires real external credentials/resources and an executed evidence artifact"
                ),
            },
        ).as_dict()
        for name, scope, status in _EXTERNAL_CAPABILITIES
    ]
    records = [*local, *independent, *external]
    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    return {
        "schema_version": 1,
        "commit_sha": sha,
        "local_gate_passed": bool(local_gate_passed),
        "superior": False,
        "records": records,
        "counts": counts,
        "truthfulness": {
            "local_certification_applies_only_to_this_exact_commit": True,
            "coco_status_requires_independent_exact_head_workflow": True,
            "external_status_never_inferred_from_local_tests": True,
            "superiority_requires_separate_executed_comparative_benchmark": True,
            "ade_bench_score_claimed": False,
        },
    }


def write_competitive_ledger(
    path: str | Path,
    commit_sha: str,
    *,
    local_gate_passed: bool = False,
    workflow: Mapping[str, Any] | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ledger = build_competitive_ledger(
        commit_sha,
        local_gate_passed=local_gate_passed,
        workflow=workflow,
    )
    destination.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination