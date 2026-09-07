from __future__ import annotations

import subprocess

from agentic_data_platform.onboarding import materialize_sample
from agentic_data_platform.tools.feedback import submit_feedback


def test_sample_setup_materialize_reuse_conflict_and_alongside(tmp_path):
    first = materialize_sample(home=tmp_path)
    assert first["status"] == "PASS"
    assert first["reused"] is False
    target = tmp_path / "agentic-data-sample-dbt"
    assert (target / "dbt_project.yml").is_file()
    assert (target / "models" / "fct_orders.sql").is_file()
    assert (target / "seeds" / "raw_orders.csv").is_file()

    reused = materialize_sample(home=tmp_path)
    assert reused["status"] == "PASS"
    assert reused["reused"] is True

    (target / ".sample-manifest.json").write_text(
        '{"name":"agentic-data-sample-dbt","version":"0.9.0"}'
    )
    conflict = materialize_sample(home=tmp_path)
    assert conflict["status"] == "VERSION_CONFLICT"

    alongside = materialize_sample(
        home=tmp_path,
        install_alongside=True,
    )
    assert alongside["status"] == "PASS"
    assert alongside["suffix"] == 2
    assert (tmp_path / "agentic-data-sample-dbt-2").is_dir()


def test_sample_setup_rejects_unsafe_target_names(tmp_path):
    for name in ("../escape", ".hidden", "nested/path"):
        try:
            materialize_sample(home=tmp_path, preferred_target_name=name)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe sample target accepted: {name}")


def test_feedback_reports_external_skips_without_gh():
    def runner(argv):
        if argv[:2] == ["gh", "--version"]:
            return subprocess.CompletedProcess(argv, 127, "", "not found")
        raise AssertionError(argv)

    result = submit_feedback(
        title="Bug",
        category="bug",
        description="Something failed.",
        runner=runner,
    )
    assert result["status"] == "SKIP_EXTERNAL"
    assert result["error"] == "gh_not_installed"


def test_feedback_submission_uses_labels_and_falls_back_without_them():
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[:2] == ["gh", "--version"]:
            return subprocess.CompletedProcess(argv, 0, "gh version 2.0\n", "")
        if argv[:3] == ["gh", "auth", "status"]:
            return subprocess.CompletedProcess(argv, 0, "ok", "")
        if "--label" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "label missing")
        return subprocess.CompletedProcess(
            argv,
            0,
            "https://github.com/acme/demo/issues/1\n",
            "",
        )

    result = submit_feedback(
        title="Feature",
        category="feature",
        description="Please add this.",
        repository="acme/demo",
        runner=runner,
    )
    assert result["status"] == "PASS"
    assert result["issue_url"].endswith("/issues/1")
    assert any("--label" in call for call in calls)
    assert any(call[:3] == ["gh", "issue", "create"] and "--label" not in call for call in calls)
