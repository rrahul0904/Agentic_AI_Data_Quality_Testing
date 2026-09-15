from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api import create_app
from agentic_data_platform.certification.production import (
    AssuranceStatus,
    build_production_certification,
    load_external_evidence,
)


SHA = "a" * 40


def _external_record(*, status: str = "PASS_EXTERNAL", commit_sha: str = SHA) -> dict[str, object]:
    return {
        "status": status,
        "commit_sha": commit_sha,
        "executed_at": "2026-09-15T03:00:00Z",
        "artifact_uri": "s3://ade-certification/example.json",
        "evidence_sha256": hashlib.sha256(b"evidence").hexdigest(),
    }


def test_requires_exact_commit_sha() -> None:
    with pytest.raises(ValueError, match="exact 40-character Git SHA"):
        build_production_certification("main", local_gate_passed=True)


def test_local_gate_never_infers_external_pass() -> None:
    payload = build_production_certification(SHA, local_gate_passed=True)
    assert payload["local_gate_passed"] is True
    assert payload["superior"] is False
    local = [record for record in payload["records"] if record["track"] == "LOCAL_PRODUCTION"]
    external = [record for record in payload["records"] if record["track"] == "EXTERNAL_ASSURANCE"]
    assert local
    assert external
    assert {record["status"] for record in local} == {AssuranceStatus.CERTIFIED_LOCAL.value}
    assert {record["status"] for record in external} == {AssuranceStatus.NOT_RUN_EXTERNAL.value}


def test_invalid_external_evidence_fails_closed() -> None:
    payload = build_production_certification(
        SHA,
        external_evidence={
            "snowflake_cortex_search_live": {
                "status": "PASS_EXTERNAL",
                "artifact_uri": "s3://missing-hash.json",
            }
        },
    )
    record = next(
        item for item in payload["records"] if item["capability"] == "snowflake_cortex_search_live"
    )
    assert record["status"] == AssuranceStatus.BLOCKED_EXTERNAL.value
    assert payload["superior"] is False


def test_malformed_external_track_payload_fails_closed(tmp_path) -> None:
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(
        json.dumps({"snowflake_cortex_search_live": "not-an-evidence-object"}),
        encoding="utf-8",
    )
    external = load_external_evidence(evidence_file)
    assert external["snowflake_cortex_search_live"] == "not-an-evidence-object"

    payload = build_production_certification(SHA, external_evidence=external)
    record = next(
        item for item in payload["records"] if item["capability"] == "snowflake_cortex_search_live"
    )
    assert record["status"] == AssuranceStatus.BLOCKED_EXTERNAL.value
    assert record["evidence"]["supplied"] == "not-an-evidence-object"
    assert payload["superior"] is False


def test_external_evidence_from_another_commit_fails_closed() -> None:
    payload = build_production_certification(
        SHA,
        external_evidence={
            "snowflake_cortex_search_live": _external_record(commit_sha="b" * 40),
        },
    )
    record = next(
        item for item in payload["records"] if item["capability"] == "snowflake_cortex_search_live"
    )
    assert record["status"] == AssuranceStatus.BLOCKED_EXTERNAL.value
    assert record["evidence"]["commit_sha"] == SHA
    assert payload["superior"] is False


def test_valid_external_pass_is_preserved_without_implying_superiority() -> None:
    payload = build_production_certification(
        SHA,
        external_evidence={"snowflake_cortex_search_live": _external_record()},
    )
    record = next(
        item for item in payload["records"] if item["capability"] == "snowflake_cortex_search_live"
    )
    assert record["status"] == AssuranceStatus.PASS_EXTERNAL.value
    assert record["evidence"]["commit_sha"] == SHA
    assert payload["superior"] is False


def test_superiority_requires_executed_winning_comparative_metrics() -> None:
    evidence = _external_record()
    evidence["metrics"] = {
        "winner": "ADE",
        "ade_score": 0.91,
        "competitor_scores": {"competitor-a": 0.81, "competitor-b": 0.87},
    }
    payload = build_production_certification(
        SHA,
        external_evidence={"cross_product_superiority_benchmark": evidence},
    )
    assert payload["superior"] is True


def test_superiority_stays_false_when_ade_does_not_win() -> None:
    evidence = _external_record()
    evidence["metrics"] = {
        "winner": "ADE",
        "ade_score": 0.80,
        "competitor_scores": {"competitor-a": 0.85},
    }
    payload = build_production_certification(
        SHA,
        external_evidence={"cross_product_superiority_benchmark": evidence},
    )
    assert payload["superior"] is False


def test_superiority_stays_false_for_evidence_from_another_commit() -> None:
    evidence = _external_record(commit_sha="b" * 40)
    evidence["metrics"] = {
        "winner": "ADE",
        "ade_score": 0.91,
        "competitor_scores": {"competitor-a": 0.81},
    }
    payload = build_production_certification(
        SHA,
        external_evidence={"cross_product_superiority_benchmark": evidence},
    )
    assert payload["superior"] is False


def test_load_external_evidence_requires_object(tmp_path) -> None:
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="root must be a JSON object"):
        load_external_evidence(evidence_file)


def test_runtime_api_is_unbound_without_build_sha(monkeypatch) -> None:
    monkeypatch.delenv("ADE_COMMIT_SHA", raising=False)
    monkeypatch.delenv("ADE_EXTERNAL_ASSURANCE_EVIDENCE", raising=False)
    client = TestClient(create_app())
    response = client.get("/api/v1/certification/production")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNBOUND_RUNTIME"
    assert body["superior"] is False


def test_runtime_api_reports_but_does_not_self_certify(monkeypatch) -> None:
    monkeypatch.setenv("ADE_COMMIT_SHA", SHA)
    monkeypatch.delenv("ADE_EXTERNAL_ASSURANCE_EVIDENCE", raising=False)
    client = TestClient(create_app())
    response = client.get("/api/v1/certification/production")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REPORT_ONLY"
    assert body["commit_sha"] == SHA
    assert body["local_gate_passed"] is False
    assert body["superior"] is False


def test_runtime_api_blocks_missing_configured_external_evidence(monkeypatch, tmp_path) -> None:
    missing_file = tmp_path / "missing.json"
    monkeypatch.setenv("ADE_COMMIT_SHA", SHA)
    monkeypatch.setenv("ADE_EXTERNAL_ASSURANCE_EVIDENCE", str(missing_file))

    client = TestClient(create_app())
    response = client.get("/api/v1/certification/production")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == AssuranceStatus.BLOCKED_EXTERNAL.value
    assert body["superior"] is False
    external = [record for record in body["records"] if record["track"] == "EXTERNAL_ASSURANCE"]
    assert external
    assert {record["status"] for record in external} == {AssuranceStatus.BLOCKED_EXTERNAL.value}
    assert body["truthfulness"]["external_evidence_load_failed"] is True


def test_runtime_api_blocks_malformed_external_evidence(monkeypatch, tmp_path) -> None:
    evidence_file = tmp_path / "malformed.json"
    evidence_file.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("ADE_COMMIT_SHA", SHA)
    monkeypatch.setenv("ADE_EXTERNAL_ASSURANCE_EVIDENCE", str(evidence_file))

    client = TestClient(create_app())
    response = client.get("/api/v1/certification/production")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == AssuranceStatus.BLOCKED_EXTERNAL.value
    assert body["superior"] is False
    external = [record for record in body["records"] if record["track"] == "EXTERNAL_ASSURANCE"]
    assert external
    assert {record["status"] for record in external} == {AssuranceStatus.BLOCKED_EXTERNAL.value}
    assert body["counts"][AssuranceStatus.BLOCKED_EXTERNAL.value] == len(external)
    assert body["truthfulness"]["external_evidence_load_failed"] is True
