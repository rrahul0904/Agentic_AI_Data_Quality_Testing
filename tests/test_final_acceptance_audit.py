from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "final_acceptance_audit.py"


def _module():
    spec = importlib.util.spec_from_file_location("final_acceptance_audit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_final_acceptance_audit_current_repository_passes():
    module = _module()
    files = module.tracked_files()
    security, scanned = module.security_audit(files)
    debt, markers = module.product_debt_audit(files)
    assert scanned > 0
    assert security == []
    assert debt == []
    assert set(markers) >= {"TODO", "FIXME", "HACK", "NotImplemented"}


def test_secret_patterns_are_high_signal_and_redacted():
    module = _module()
    assert module.HIGH_SIGNAL_SECRET_PATTERNS["aws_access_key"].search("AKIA1234567890ABCDEF")
    assert module.HIGH_SIGNAL_SECRET_PATTERNS["credential_url"].search("postgres://user:pass@example.test/db")
    assert "value" not in {"rule_id": "secret", "file": "x", "line": 1}


def test_audit_safe_fixture_marker_is_line_scoped():
    module = _module()
    text = (
        "safe = 'postgres://user:pass@example.test/db'  # audit-safe-fixture\n"
        "unsafe = 'postgres://user:pass@example.test/db'\n"
    )
    pattern = module.HIGH_SIGNAL_SECRET_PATTERNS["credential_url"]
    matches = list(pattern.finditer(text))
    assert len(matches) == 2
    assert module._match_is_audit_safe_fixture(text, matches[0].start()) is True
    assert module._match_is_audit_safe_fixture(text, matches[1].start()) is False
