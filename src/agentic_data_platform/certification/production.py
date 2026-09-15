"""Production-readiness and external-assurance certification with fail-closed evidence rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class AssuranceStatus(str, Enum):
    IMPLEMENTED_UNCERTIFIED = "IMPLEMENTED_UNCERTIFIED"
    CERTIFIED_LOCAL = "CERTIFIED_LOCAL"
    NOT_RUN_EXTERNAL = "NOT_RUN_EXTERNAL"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    PASS_EXTERNAL = "PASS_EXTERNAL"
    FAIL_EXTERNAL = "FAIL_EXTERNAL"


@dataclass(frozen=True)
class AssuranceRecord:
    capability: str
    track: str
    status: AssuranceStatus
    evidence: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


_LOCAL_TRACKS = (
    "production_web_api_container_topology",
    "same_origin_operator_api_proxy",
    "portable_docker_kubernetes_spcs_planning",
    "governed_agent_approval_contracts",
    "deterministic_search_sql_lineage_regressions",
    "desktop_packaging_contract",
)

_EXTERNAL_TRACKS = (
    "snowflake_cortex_search_live",
    "snowflake_ai_parse_document_live",
    "snowflake_spcs_gpu_live",
    "external_embedding_reranker_live",
    "external_llm_provider_live",
    "managed_staging_deployment",
    "cross_product_superiority_benchmark",
)

_REQUIRED_EXTERNAL_FIELDS = (
    "commit_sha",
    "executed_at",
    "artifact_uri",
    "evidence_sha256",
)


def _valid_external_evidence(record: Mapping[str, Any], *, expected_commit_sha: str) -> bool:
    if record.get("status") not in {"PASS_EXTERNAL", "FAIL_EXTERNAL"}:
        return False
    if any(not str(record.get(field, "")).strip() for field in _REQUIRED_EXTERNAL_FIELDS):
        return False
    evidence_commit_sha = str(record.get("commit_sha", "")).strip()
    if not _SHA.fullmatch(evidence_commit_sha):
        return False
    if evidence_commit_sha.lower() != expected_commit_sha.lower():
        return False
    return bool(_SHA256.fullmatch(str(record.get("evidence_sha256", "")).strip()))


def _superiority_proven(record: Mapping[str, Any], *, expected_commit_sha: str) -> bool:
    if (
        record.get("status") != "PASS_EXTERNAL"
        or not _valid_external_evidence(record, expected_commit_sha=expected_commit_sha)
    ):
        return False
    metrics = record.get("metrics")
    if not isinstance(metrics, Mapping):
        return False
    competitor_scores = metrics.get("competitor_scores")
    if not isinstance(competitor_scores, Mapping) or not competitor_scores:
        return False
    try:
        ade_score = float(metrics["ade_score"])
        best_competitor = max(float(value) for value in competitor_scores.values())
    except (KeyError, TypeError, ValueError):
        return False
    return str(metrics.get("winner", "")).upper() == "ADE" and ade_score > best_competitor


def build_production_certification(
    commit_sha: str,
    *,
    local_gate_passed: bool = False,
    external_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an exact-head assurance ledger without inferring external success from local CI."""

    sha = str(commit_sha).strip()
    if not _SHA.fullmatch(sha):
        raise ValueError("commit_sha must be an exact 40-character Git SHA")

    local_status = (
        AssuranceStatus.CERTIFIED_LOCAL
        if local_gate_passed
        else AssuranceStatus.IMPLEMENTED_UNCERTIFIED
    )
    records: list[dict[str, Any]] = [
        AssuranceRecord(
            capability=capability,
            track="LOCAL_PRODUCTION",
            status=local_status,
            evidence={"commit_sha": sha, "local_gate_passed": bool(local_gate_passed)},
        ).as_dict()
        for capability in _LOCAL_TRACKS
    ]

    external = dict(external_evidence or {})
    for capability in _EXTERNAL_TRACKS:
        supplied = external.get(capability)
        if supplied is None:
            status = AssuranceStatus.NOT_RUN_EXTERNAL
            evidence: Mapping[str, Any] = {
                "commit_sha": sha,
                "reason": "requires a real executed external run and immutable evidence artifact",
            }
        elif isinstance(supplied, Mapping) and _valid_external_evidence(
            supplied, expected_commit_sha=sha
        ):
            status = AssuranceStatus(str(supplied["status"]))
            evidence = {**dict(supplied), "commit_sha": sha}
        else:
            status = AssuranceStatus.BLOCKED_EXTERNAL
            evidence = {
                "commit_sha": sha,
                "reason": "external evidence was supplied but failed the exact-head evidence contract",
                "supplied": dict(supplied) if isinstance(supplied, Mapping) else supplied,
            }
        records.append(
            AssuranceRecord(
                capability=capability,
                track="EXTERNAL_ASSURANCE",
                status=status,
                evidence=evidence,
            ).as_dict()
        )

    superiority_record = external.get("cross_product_superiority_benchmark", {})
    superior = (
        _superiority_proven(superiority_record, expected_commit_sha=sha)
        if isinstance(superiority_record, Mapping)
        else False
    )
    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1

    return {
        "schema_version": 1,
        "commit_sha": sha,
        "local_gate_passed": bool(local_gate_passed),
        "superior": superior,
        "records": records,
        "counts": counts,
        "truthfulness": {
            "exact_head_only": True,
            "local_ci_never_implies_external_pass": True,
            "external_pass_requires_matching_commit_executed_at_artifact_uri_and_sha256": True,
            "superiority_requires_executed_comparative_metrics": True,
        },
    }


def load_external_evidence(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("external evidence root must be a JSON object")
    return {str(key): value for key, value in payload.items()}


def write_production_certification(
    path: str | Path,
    commit_sha: str,
    *,
    local_gate_passed: bool = False,
    external_evidence: Mapping[str, Any] | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_production_certification(
        commit_sha,
        local_gate_passed=local_gate_passed,
        external_evidence=external_evidence,
    )
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def evidence_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
