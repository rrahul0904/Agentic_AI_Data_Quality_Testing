from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from agentic_data_platform.acp_server import ADEACPAgent
from agentic_data_platform.compute import ComputeJobSpec, PortableComputePlanner, PortableComputeRunner
from agentic_data_platform.connectors.models import QueryResult
from agentic_data_platform.knowledge import (
    DocumentExtraction,
    provider_structured_extraction,
    snowflake_parse_document_sql,
)
from agentic_data_platform.models import Capability, Platform, Risk
from agentic_data_platform.providers.base import ProviderResponse, Usage
from agentic_data_platform.remote_workspace import RemoteWorkspaceConfig, SSHRemoteWorkspace
from agentic_data_platform.retrieval import CortexSearchBackend, HybridRetrievalBackend, RetrievalQuery
from agentic_data_platform.sdk import ADEClient, ToolApprovalRequest
from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry


class FakeSnowflake:
    platform = "snowflake"

    def __init__(self, rows=()):
        self.rows = tuple(rows)
        self.sql = []

    def execute_read(self, sql):
        self.sql.append(sql)
        return QueryResult(self.rows, query_id="q-test")


class FakeProvider:
    name = "fake-provider"

    def generate(self, request):
        assert "invoice_id" in request.messages[-1]["content"]
        return ProviderResponse(
            content=(
                '{"invoice_id":"INV-42","total":19.5,"unexpected":"ignored",'
                '"_ade_evidence":{"invoice_id":{"quote":"INV-42","confidence":0.93}}}'
            ),
            usage=Usage(input_tokens=100, output_tokens=20, cost_usd=0.001),
            finish_reason="stop",
        )


def test_cortex_search_backend_and_hybrid_fusion_are_evidence_preserving():
    connector = FakeSnowflake(
        ({"results": json.dumps([{"text": "refund revenue rule", "source": "policy.md"}])},)
    )
    backend = CortexSearchBackend(connector, "DB.SCHEMA.SEARCH_SERVICE", default_columns=("text", "source"))
    hits = backend.search(RetrievalQuery("refund revenue", limit=5))
    assert len(hits) == 1
    assert hits[0].source == "policy.md"
    assert hits[0].fingerprint
    assert hits[0].evidence["query_id"] == "q-test"
    assert "SNOWFLAKE.CORTEX.SEARCH_PREVIEW" in connector.sql[0]
    assert "DB.SCHEMA.SEARCH_SERVICE" in connector.sql[0]

    hybrid = HybridRetrievalBackend([backend])
    fused = hybrid.search(RetrievalQuery("refund revenue", limit=1))
    assert fused[0].backend == "hybrid"
    assert fused[0].evidence["fusion"] == "reciprocal_rank"


def test_sdk_exposes_fingerprint_bound_tool_approval(tmp_path):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test_mutation",
            capability=Capability.EXECUTE,
            risk=Risk.MUTATING,
            supported_platforms=frozenset({Platform.LOCAL}),
            requires_approval=True,
            handler=lambda args: {"changed": args["value"], "approved": args["_approved"]},
        )
    )
    client = ADEClient(tmp_path, registry=registry)
    session = client.session(auto_index=False)

    blocked = session.invoke_tool("test_mutation", {"value": 7}, platform="local")
    assert blocked["status"] == "APPROVAL_REQUIRED"
    assert len(blocked["approval"]["fingerprint"]) == 64

    observed: list[ToolApprovalRequest] = []
    result = session.invoke_tool(
        "test_mutation",
        {"value": 7},
        platform="local",
        approval_callback=lambda request: observed.append(request) or True,
    )
    assert result["status"] == "PASS"
    assert result["result"] == {"changed": 7, "approved": True}
    assert observed[0].fingerprint == result["approval_fingerprint"]


def test_compute_plans_are_portable_fingerprinted_and_approval_bound(tmp_path):
    spec = ComputeJobSpec(
        name="qualityscan",
        image="example/quality:1.0",
        command=("python", "scan.py"),
        cpu=2,
        memory_gib=4,
        gpu=1,
        workspace=str(tmp_path),
    )
    planner = PortableComputePlanner()
    docker = planner.docker(spec)
    assert docker.command[0:2] == ("docker", "run")
    assert "--gpus" in docker.command
    assert len(docker.fingerprint) == 64

    k8s = planner.kubernetes(spec, namespace="ade")
    container = k8s.manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"]["limits"]["nvidia.com/gpu"] == 1
    assert k8s.manifest["spec"]["template"]["spec"]["automountServiceAccountToken"] is False

    snowflake = planner.snowflake_spcs(spec, compute_pool="GPU_POOL", job_name="ADE_JOB")
    assert "EXECUTE JOB SERVICE" in snowflake.sql
    assert "IN COMPUTE POOL GPU_POOL" in snowflake.sql
    assert "nvidia.com/gpu" in snowflake.sql

    runner = PortableComputeRunner()
    assert runner.execute(docker)["status"] == "APPROVAL_REQUIRED"


def test_remote_workspace_confines_paths_and_gates_mutation():
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="a.sql\nb.sql\n", stderr="")

    workspace = SSHRemoteWorkspace(
        RemoteWorkspaceConfig(host="example.internal", user="ade", root="/srv/project"),
        runner=fake_run,
    )
    assert workspace.list_files()["count"] == 2
    assert workspace.write_text("models/a.sql", "select 1")["status"] == "APPROVAL_REQUIRED"
    approved = workspace.write_text("models/a.sql", "select 1", approved=True)
    assert approved["status"] == "PASS"
    assert commands
    with pytest.raises(ValueError):
        workspace.read_text("../etc/passwd")


def test_document_intelligence_supports_provider_and_snowflake_paths():
    extraction = DocumentExtraction(
        source="invoice.txt",
        source_type="txt",
        text="Invoice INV-42 total 19.5",
        metadata={"characters": 25},
    )
    result = provider_structured_extraction(
        extraction,
        FakeProvider(),
        "fake-model",
        {"invoice_id": "invoice identifier", "total": "invoice total"},
    )
    assert result.status == "PASS"
    assert result.extracted == {"invoice_id": "INV-42", "total": 19.5}
    assert result.provenance["unexpected_fields_ignored"] == ["unexpected"]
    invoice_evidence = result.provenance["field_evidence"]["invoice_id"]
    assert invoice_evidence["source_evidence"] == "provider_quote_verified"
    assert invoice_evidence["confidence"] == 0.93
    assert invoice_evidence["confidence_source"] == "provider_supplied"
    total_evidence = result.provenance["field_evidence"]["total"]
    assert total_evidence["source_evidence"] == "exact_literal_verified"
    assert total_evidence["confidence"] is None
    assert total_evidence["confidence_source"] == "not_provided"

    sql = snowflake_parse_document_sql(
        "@DB.SCHEMA.DOCS",
        "invoices/a.pdf",
        mode="LAYOUT",
        page_split=True,
        extract_images=True,
    )
    assert "AI_PARSE_DOCUMENT" in sql
    assert "TO_FILE('@DB.SCHEMA.DOCS', 'invoices/a.pdf')" in sql
    assert "'extract_images', TRUE" in sql


def test_acp_agent_negotiates_official_protocol(tmp_path):
    agent = ADEACPAgent()
    initialized = asyncio.run(agent.initialize(protocol_version=1))
    assert initialized.protocol_version
    assert initialized.agent_info.name == "ade"

    created = asyncio.run(agent.new_session(cwd=str(tmp_path), mcp_servers=[]))
    assert created.session_id.startswith("session_")
    assert created.session_id in agent._sessions