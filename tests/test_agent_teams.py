from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from agentic_data_platform.agents.teams import TeamCoordinator, TeamStore
from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.teammates import TeammateStore
from agentic_data_platform.tools.builtin import build_tool_registry


def _stores(tmp_path):
    path = tmp_path / "teams.db"
    return TeamStore(path), TeammateStore(path)


def _member(
    teammates: TeammateStore,
    name: str,
    *,
    role: str,
    allowed_tools=(),
    verification=(),
    actor_mode="analyst",
):
    return teammates.create(
        name,
        role=role,
        allowed_tools=allowed_tools,
        budgets={"max_steps": 6, "timeout_seconds": 90},
        verification=verification,
        actor_mode=actor_mode,
        model="fixture-model",
        system_prompt=f"You are the {role}.",
    )


def test_team_persists_members_and_policy_fingerprint(tmp_path):
    teams, teammates = _stores(tmp_path)
    snowflake = _member(
        teammates,
        "Snowflake Investigator",
        role="warehouse investigator",
        allowed_tools=["snowflake_pipeline_rca", "semantic_search"],
    )
    dbt = _member(
        teammates,
        "dbt Reviewer",
        role="transformation reviewer",
        allowed_tools=["dbt_failed_models"],
    )
    team = teams.create("Pipeline RCA", max_parallel=2)
    team = teams.set_members(
        team["team_id"],
        [snowflake["teammate_id"], dbt["teammate_id"]],
    )

    assert team["members"] == [snowflake["teammate_id"], dbt["teammate_id"]]
    assert team["team_fingerprint"]
    assert teammates.get(snowflake["teammate_id"])["role"] == "warehouse investigator"
    assert teammates.get(snowflake["teammate_id"])["allowed_tools"] == [
        "semantic_search",
        "snowflake_pipeline_rca",
    ]


def test_team_plan_is_dependency_validated_and_hash_bound(tmp_path):
    teams, teammates = _stores(tmp_path)
    first = _member(teammates, "One", role="investigator")
    second = _member(teammates, "Two", role="reviewer")
    team = teams.create("DAG")
    teams.set_members(team["team_id"], [first["teammate_id"], second["teammate_id"]])

    coordinator = TeamCoordinator(teams, teammates, lambda _: {"status": "PASS"})
    plan = coordinator.plan(
        team["team_id"],
        [
            {
                "task_id": "inspect",
                "teammate_id": first["teammate_id"],
                "prompt": "Inspect evidence",
            },
            {
                "task_id": "review",
                "teammate_id": second["teammate_id"],
                "prompt": "Review evidence",
                "depends_on": ["inspect"],
            },
        ],
    )

    assert plan["status"] == "PASS"
    assert plan["approval_fingerprint"]
    assert plan["tasks"][1]["depends_on"] == ["inspect"]
    assert plan["member_contracts"][first["teammate_id"]]["budgets"]["max_steps"] == 6


def test_team_rejects_cycles_nonmembers_and_stale_team(tmp_path):
    teams, teammates = _stores(tmp_path)
    first = _member(teammates, "One", role="investigator")
    second = _member(teammates, "Two", role="reviewer")
    outsider = _member(teammates, "Outsider", role="outsider")
    team = teams.create("Guards")
    teams.set_members(team["team_id"], [first["teammate_id"], second["teammate_id"]])
    coordinator = TeamCoordinator(teams, teammates, lambda _: {"status": "PASS"})

    try:
        coordinator.plan(
            team["team_id"],
            [{
                "task_id": "outside",
                "teammate_id": outsider["teammate_id"],
                "prompt": "Should fail",
            }],
        )
    except ValueError as exc:
        assert "not a member" in str(exc)
    else:
        raise AssertionError("non-member task should fail")

    try:
        coordinator.plan(
            team["team_id"],
            [
                {
                    "task_id": "a",
                    "teammate_id": first["teammate_id"],
                    "prompt": "A",
                    "depends_on": ["b"],
                },
                {
                    "task_id": "b",
                    "teammate_id": second["teammate_id"],
                    "prompt": "B",
                    "depends_on": ["a"],
                },
            ],
        )
    except ValueError as exc:
        assert "dependency cycle" in str(exc)
    else:
        raise AssertionError("cyclic team task plan should fail")

    valid = coordinator.plan(
        team["team_id"],
        [{
            "task_id": "a",
            "teammate_id": first["teammate_id"],
            "prompt": "A",
        }],
    )
    teams.edit(team["team_id"], max_parallel=3)
    stale = coordinator.run(valid, approval_fingerprint=valid["approval_fingerprint"])
    assert stale["status"] == "STALE_TEAM"


def test_team_executes_parallel_ready_tasks_then_dependency_wave(tmp_path):
    teams, teammates = _stores(tmp_path)
    first = _member(
        teammates,
        "Warehouse",
        role="warehouse",
        verification=[{"field": "verified", "equals": True}],
    )
    second = _member(
        teammates,
        "Airflow",
        role="orchestration",
        verification=[{"field": "verified", "equals": True}],
    )
    reviewer = _member(
        teammates,
        "Reviewer",
        role="reviewer",
        verification=[{"field": "verified", "equals": True}],
    )
    team = teams.create("Parallel RCA", max_parallel=2)
    teams.set_members(
        team["team_id"],
        [first["teammate_id"], second["teammate_id"], reviewer["teammate_id"]],
    )

    barrier = threading.Barrier(2, timeout=3)
    calls = []

    def execute(task):
        task_id = task.metadata["task_id"]
        calls.append(task_id)
        if task_id in {"snowflake", "airflow"}:
            barrier.wait()
        return {
            "status": "PASS",
            "summary": f"finished {task_id}",
            "verified": True,
            "evidence": [f"evidence:{task_id}"],
        }

    coordinator = TeamCoordinator(teams, teammates, execute)
    plan = coordinator.plan(
        team["team_id"],
        [
            {
                "task_id": "snowflake",
                "teammate_id": first["teammate_id"],
                "prompt": "Inspect warehouse",
            },
            {
                "task_id": "airflow",
                "teammate_id": second["teammate_id"],
                "prompt": "Inspect orchestration",
            },
            {
                "task_id": "synthesis",
                "teammate_id": reviewer["teammate_id"],
                "prompt": "Synthesize RCA",
                "depends_on": ["snowflake", "airflow"],
            },
        ],
    )
    result = coordinator.run(
        plan,
        approval_fingerprint=plan["approval_fingerprint"],
    )

    assert result["status"] == "PASS"
    assert result["waves"] == [["snowflake", "airflow"], ["synthesis"]]
    assert calls[-1] == "synthesis"
    assert result["failed_count"] == 0
    assert result["evidence_fingerprint"]
    stored = teams.run(result["run_id"])
    assert stored["status"] == "PASS"
    assert stored["evidence_fingerprint"] == result["evidence_fingerprint"]


def test_failed_team_task_blocks_dependents_and_records_verification(tmp_path):
    teams, teammates = _stores(tmp_path)
    worker = _member(
        teammates,
        "Worker",
        role="worker",
        verification=[{"field": "verified", "equals": True}],
    )
    reviewer = _member(teammates, "Reviewer", role="reviewer")
    team = teams.create("Failure handling")
    teams.set_members(team["team_id"], [worker["teammate_id"], reviewer["teammate_id"]])

    def execute(task):
        if task.metadata["task_id"] == "work":
            return {"status": "PASS", "summary": "unverified", "verified": False}
        return {"status": "PASS", "summary": "should not run"}

    coordinator = TeamCoordinator(teams, teammates, execute)
    plan = coordinator.plan(
        team["team_id"],
        [
            {
                "task_id": "work",
                "teammate_id": worker["teammate_id"],
                "prompt": "Work",
            },
            {
                "task_id": "review",
                "teammate_id": reviewer["teammate_id"],
                "prompt": "Review",
                "depends_on": ["work"],
            },
        ],
    )
    result = coordinator.run(plan, approval_fingerprint=plan["approval_fingerprint"])

    assert result["status"] == "FAIL"
    by_id = {item["task_id"]: item for item in result["results"]}
    assert by_id["work"]["status"] == "FAIL_VERIFICATION"
    assert by_id["work"]["verification"]["status"] == "FAIL"
    assert by_id["review"]["status"] == "BLOCKED_DEPENDENCY"


def test_team_stale_approval_does_not_start_durable_run(tmp_path):
    teams, teammates = _stores(tmp_path)
    worker = _member(teammates, "Worker", role="worker")
    team = teams.create("Approval")
    teams.set_members(team["team_id"], [worker["teammate_id"]])
    coordinator = TeamCoordinator(teams, teammates, lambda _: {"status": "PASS"})
    plan = coordinator.plan(
        team["team_id"],
        [{
            "task_id": "work",
            "teammate_id": worker["teammate_id"],
            "prompt": "Work",
        }],
    )

    result = coordinator.run(plan, approval_fingerprint="tampered")
    assert result["status"] == "STALE_APPROVAL"
    assert teams.runs(team["team_id"]) == []


def test_team_tools_and_api_domain_are_exposed():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "team_list",
        "team_show",
        "team_create",
        "team_edit",
        "team_set_members",
        "team_delete",
        "team_plan",
        "team_run",
        "team_runs",
        "team_run_show",
    } <= names

    expected = {
        "list",
        "show",
        "create",
        "edit",
        "members",
        "delete",
        "plan",
        "run",
        "runs",
        "run-show",
    }
    assert set(DOMAIN_CLI_TOOLS["teams"]) == expected

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    assert set(response.json()["teams"]) == {
        *expected,
    }
