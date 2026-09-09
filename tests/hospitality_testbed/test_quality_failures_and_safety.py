from __future__ import annotations

import os
import subprocess
import sys

import yaml

from certify_failure_accuracy import compare
from lib import ROOT, redact
from stage_failure_fixture import generate


def test_failure_fixtures_cover_ground_truth(tmp_path):
    scenarios = yaml.safe_load((ROOT / "config/hospitality_failure_scenarios.yml").read_text())["scenarios"]
    result = generate(tmp_path, list(scenarios))
    assert result["status"] == "PASS"
    assert len(result["scenarios"]) == 18
    assert (tmp_path / "zero_byte_file/reservation_zero_byte_file.csv").stat().st_size == 0
    assert (tmp_path / "corrupt_parquet/stays_corrupt.parquet").read_bytes().startswith(b"PAR1")


def test_failure_accuracy_never_claims_unexecuted_pass():
    truth = {"scenarios": [{"scenario": "invalid_timestamp", "expected_divergence": "SNOWPIPE_LOAD"}]}
    result = compare(truth, {"scenarios": []})
    assert result["status"] == "NOT_RUN"
    assert result["accuracy_pct"] is None


def test_secret_redaction_is_recursive():
    value = redact({"password": "secret", "nested": {"api_token": "token"}, "safe": "visible"})
    assert value == {"password": "***REDACTED***", "nested": {"api_token": "***REDACTED***"}, "safe": "visible"}


def test_mutating_failure_stage_is_blocked_without_approval(tmp_path):
    env = {**os.environ, "ADE_TESTBED_MUTATION_APPROVED": "false"}
    process = subprocess.run([sys.executable, str(ROOT / "scripts/hospitality_testbed/stage_failure_fixture.py"), "--scenario", "invalid_timestamp", "--stage", "--output", str(tmp_path)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert process.returncode == 0
    assert '"status": "BLOCKED_APPROVAL"' in process.stdout


def test_external_scripts_fail_closed_without_credentials(monkeypatch):
    env = {key: value for key, value in os.environ.items() if not key.startswith("ADE_SNOWFLAKE_")}
    process = subprocess.run([sys.executable, str(ROOT / "scripts/hospitality_testbed/certify_with_ade.py")], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert process.returncode == 0
    assert "BLOCKED_EXTERNAL" in process.stdout
