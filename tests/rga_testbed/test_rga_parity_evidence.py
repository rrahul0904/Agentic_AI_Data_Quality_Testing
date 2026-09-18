from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_evidence(evidence_dir: Path, case: dict, consumer: str, rows: list[dict], security_context: str = "ROLE_ANALYST"):
    payload = {
        "case_id": case["id"],
        "consumer": consumer,
        "security_context": security_context,
        "rows": rows,
    }
    (evidence_dir / f"{case['id']}.{consumer}.json").write_text(json.dumps(payload), encoding="utf-8")


def _sample_rows(case: dict) -> list[dict]:
    row = {}
    for index, dimension in enumerate(case["dimensions"], start=1):
        row[dimension] = f"DIM-{index}"
    for index, metric in enumerate(case["metrics"], start=1):
        row[metric] = 10.0 * index
    return [row]


def test_parity_evidence_validator_passes_identical_governed_results(tmp_path: Path):
    generator = load_module("rga_parity_gen_validator_test", ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py")
    validator = load_module("rga_parity_validator_test", ROOT / "scripts" / "rga_testbed" / "validate_parity_evidence.py")

    parity_dir = tmp_path / "parity"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    generator.generate(parity_dir, "RGA_SYNTHETIC_TESTBED")
    manifest = json.loads((parity_dir / "parity_manifest.json").read_text(encoding="utf-8"))

    for case in manifest["cases"]:
        rows = _sample_rows(case)
        for consumer in validator.CONSUMERS:
            _write_evidence(evidence_dir, case, consumer, rows)

    report = validator.validate(parity_dir / "parity_manifest.json", evidence_dir)
    assert report["status"] == "PASS"
    assert report["failed_cases"] == 0


def test_parity_evidence_validator_detects_metric_drift(tmp_path: Path):
    generator = load_module("rga_parity_gen_drift_test", ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py")
    validator = load_module("rga_parity_validator_drift_test", ROOT / "scripts" / "rga_testbed" / "validate_parity_evidence.py")

    parity_dir = tmp_path / "parity"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    generator.generate(parity_dir, "RGA_SYNTHETIC_TESTBED")
    manifest = json.loads((parity_dir / "parity_manifest.json").read_text(encoding="utf-8"))

    for case in manifest["cases"]:
        rows = _sample_rows(case)
        for consumer in validator.CONSUMERS:
            candidate = [dict(rows[0])]
            if consumer == "power_bi" and case["metrics"]:
                candidate[0][case["metrics"][0]] += 1.0
            _write_evidence(evidence_dir, case, consumer, candidate)

    report = validator.validate(parity_dir / "parity_manifest.json", evidence_dir)
    assert report["status"] == "FAIL"
    assert any(
        "power_bi" in error and "mismatch" in error
        for result in report["results"]
        for error in result["errors"]
    )


def test_parity_evidence_validator_requires_same_security_context(tmp_path: Path):
    generator = load_module("rga_parity_gen_security_test", ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py")
    validator = load_module("rga_parity_validator_security_test", ROOT / "scripts" / "rga_testbed" / "validate_parity_evidence.py")

    parity_dir = tmp_path / "parity"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    generator.generate(parity_dir, "RGA_SYNTHETIC_TESTBED")
    manifest = json.loads((parity_dir / "parity_manifest.json").read_text(encoding="utf-8"))

    for case in manifest["cases"]:
        rows = _sample_rows(case)
        for consumer in validator.CONSUMERS:
            role = "ROLE_OTHER" if consumer == "excel" else "ROLE_ANALYST"
            _write_evidence(evidence_dir, case, consumer, rows, security_context=role)

    report = validator.validate(parity_dir / "parity_manifest.json", evidence_dir)
    assert report["status"] == "FAIL"
    assert any(
        "excel: security_context mismatch" in error
        for result in report["results"]
        for error in result["errors"]
    )
