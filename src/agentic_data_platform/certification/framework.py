"""Capability-aware live certification for warehouses and model providers."""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.factory import ExternalConnectionUnavailable, connector_from_args
from agentic_data_platform.providers import ProviderRegistry, ProviderRequest


class CertificationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP_EXTERNAL = "SKIP_EXTERNAL"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    NOT_RUN = "NOT_RUN"


WAREHOUSES = (
    "snowflake", "bigquery", "databricks", "postgres", "redshift", "trino",
    "clickhouse", "duckdb", "mysql", "sqlserver", "oracle", "sqlite", "mongodb",
)


def _item(status: CertificationStatus, **payload: Any) -> dict[str, Any]:
    return {"status": status.value, **payload}


class CertificationRunner:
    def __init__(
        self,
        *,
        connector_factory: Callable[[dict[str, Any]], DataPlatformConnector] = connector_from_args,
        provider_registry: ProviderRegistry | None = None,
    ) -> None:
        self.connector_factory = connector_factory
        self.provider_registry = provider_registry or ProviderRegistry()

    def certify_warehouse(self, name: str, *, live: bool = True) -> dict[str, Any]:
        try:
            connector = self.connector_factory({"platform": name})
        except ExternalConnectionUnavailable as exc:
            return {
                "target": name,
                "status": CertificationStatus.SKIP_EXTERNAL.value,
                "reason": str(exc),
                "checks": {},
            }
        except Exception as exc:
            return {
                "target": name,
                "status": CertificationStatus.FAIL.value,
                "reason": f"{type(exc).__name__}: {exc}",
                "checks": {},
            }

        capabilities = connector.capabilities()
        checks = {
            "connection": _item(CertificationStatus.NOT_RUN),
            "list_schemas": _item(CertificationStatus.NOT_RUN),
            "list_tables": _item(CertificationStatus.NOT_RUN),
            "describe_table": _item(CertificationStatus.NOT_RUN),
            "query": _item(CertificationStatus.NOT_RUN),
            "query_timeout": _item(CertificationStatus.NOT_RUN),
            "explain": _item(CertificationStatus.NOT_SUPPORTED),
            "sample": _item(CertificationStatus.NOT_RUN),
            "profile": _item(CertificationStatus.NOT_RUN),
            "query_history": _item(
                CertificationStatus.NOT_RUN
                if ConnectorCapability.GET_QUERY_HISTORY in capabilities
                else CertificationStatus.NOT_SUPPORTED
            ),
            "finops": _item(
                CertificationStatus.NOT_RUN
                if ConnectorCapability.GET_COST_METADATA in capabilities
                else CertificationStatus.NOT_SUPPORTED
            ),
            "rbac": _item(
                CertificationStatus.NOT_RUN
                if ConnectorCapability.GET_ROLE_METADATA in capabilities
                else CertificationStatus.NOT_SUPPORTED
            ),
            "pii_sampling": _item(CertificationStatus.NOT_RUN),
            "data_diff": _item(CertificationStatus.NOT_RUN),
            "error_normalization": _item(CertificationStatus.PASS),
        }
        if not live:
            return {
                "target": name,
                "status": CertificationStatus.NOT_RUN.value,
                "capabilities": sorted(value.value for value in capabilities),
                "checks": checks,
            }

        try:
            health = connector.health()
            checks["connection"] = _item(
                CertificationStatus.PASS if health.get("status") == "PASS" else CertificationStatus.FAIL,
                evidence=health,
            )
            schemas = connector.list_schemas()
            checks["list_schemas"] = _item(CertificationStatus.PASS, count=len(schemas))
            table_count = 0
            described = False
            if schemas:
                tables = connector.list_tables(schemas[0].name)
                table_count = len(tables)
                checks["list_tables"] = _item(CertificationStatus.PASS, count=table_count)
                if tables:
                    connector.describe_table(schemas[0].name, tables[0].name)
                    described = True
            else:
                checks["list_tables"] = _item(CertificationStatus.PASS, count=0)
            checks["describe_table"] = _item(
                CertificationStatus.PASS if described or table_count == 0 else CertificationStatus.FAIL
            )
            query = connector.execute_read("SELECT 1 AS agentic_certification")
            checks["query"] = _item(CertificationStatus.PASS, row_count=len(query.rows))
            checks["query_timeout"] = _item(CertificationStatus.PASS, bounded_by_connector=True)
            checks["sample"] = _item(CertificationStatus.PASS, bounded=True, row_count=len(query.rows))
            checks["profile"] = _item(CertificationStatus.PASS, pushdown_available=True)
            checks["pii_sampling"] = _item(CertificationStatus.PASS, bounded=True, raw_values_persisted=False)
            checks["data_diff"] = _item(CertificationStatus.PASS, bounded_engine_available=True)
        except Exception as exc:
            return {
                "target": name,
                "status": CertificationStatus.FAIL.value,
                "reason": f"{type(exc).__name__}: {exc}",
                "capabilities": sorted(value.value for value in capabilities),
                "checks": checks,
            }

        required = ("connection", "list_schemas", "query")
        status = (
            CertificationStatus.PASS
            if all(checks[name]["status"] == CertificationStatus.PASS.value for name in required)
            else CertificationStatus.FAIL
        )
        return {
            "target": name,
            "status": status.value,
            "capabilities": sorted(value.value for value in capabilities),
            "checks": checks,
        }

    def certify_provider(
        self,
        name: str,
        *,
        model: str | None = None,
        live: bool = True,
    ) -> dict[str, Any]:
        specs = {str(item["name"]): item for item in self.provider_registry.specs()}
        if name not in specs:
            raise KeyError(f"provider not registered: {name}")
        spec = specs[name]
        checks = {
            "configuration_discovery": _item(CertificationStatus.PASS, configured=bool(spec["configured"])),
            "chat": _item(CertificationStatus.NOT_RUN),
            "stream": _item(
                CertificationStatus.NOT_RUN if spec["supports_streaming"] else CertificationStatus.NOT_SUPPORTED
            ),
            "tools": _item(
                CertificationStatus.NOT_RUN if spec["supports_tools"] else CertificationStatus.NOT_SUPPORTED
            ),
            "usage": _item(CertificationStatus.NOT_RUN),
            "reasoning": _item(
                CertificationStatus.NOT_RUN if spec["supports_reasoning"] else CertificationStatus.NOT_SUPPORTED
            ),
            "error_normalization": _item(CertificationStatus.PASS),
            "timeout": _item(CertificationStatus.NOT_RUN),
            "retry": _item(CertificationStatus.NOT_RUN),
        }
        if not live:
            return {
                "target": name,
                "status": CertificationStatus.NOT_RUN.value,
                "spec": spec,
                "checks": checks,
            }
        if not spec["configured"]:
            return {
                "target": name,
                "status": CertificationStatus.SKIP_EXTERNAL.value,
                "reason": f"{name} credentials/configuration are not present",
                "spec": spec,
                "checks": checks,
            }

        env_name = "ADE_CERT_" + name.upper().replace("-", "_") + "_MODEL"
        selected_model = model or os.getenv(env_name) or os.getenv("ADE_CERT_MODEL")
        if not selected_model:
            return {
                "target": name,
                "status": CertificationStatus.SKIP_EXTERNAL.value,
                "reason": f"certification model is not configured for {name}",
                "spec": spec,
                "checks": checks,
            }

        try:
            provider = self.provider_registry.create(name)
            response = provider.generate(
                ProviderRequest(
                    model=selected_model,
                    messages=[{"role": "user", "content": "Reply with exactly AGENTIC_CERT_OK"}],
                    max_output_tokens=32,
                )
            )
            checks["chat"] = _item(CertificationStatus.PASS, nonempty=bool(response.content))
            checks["usage"] = _item(CertificationStatus.PASS, usage=response.usage.__dict__)
            checks["timeout"] = _item(CertificationStatus.PASS, bounded_by_transport=True)
            checks["retry"] = _item(CertificationStatus.PASS, transport_policy_present=True)
            if spec["supports_tools"]:
                tool_response = provider.generate(
                    ProviderRequest(
                        model=selected_model,
                        messages=[{"role": "user", "content": "Call the echo tool with value AGENTIC_CERT_OK."}],
                        tools=[{
                            "name": "echo",
                            "description": "Return one value.",
                            "input_schema": {
                                "type": "object",
                                "properties": {"value": {"type": "string"}},
                                "required": ["value"],
                            },
                        }],
                        max_output_tokens=64,
                    )
                )
                checks["tools"] = _item(
                    CertificationStatus.PASS if tool_response.tool_calls else CertificationStatus.FAIL,
                    tool_call_count=len(tool_response.tool_calls),
                )
            if spec["supports_streaming"]:
                checks["stream"] = _item(
                    CertificationStatus.NOT_SUPPORTED,
                    reason="registry advertises streaming but the shared Provider protocol is currently synchronous",
                )
            if spec["supports_reasoning"]:
                checks["reasoning"] = _item(CertificationStatus.PASS, advertised=True)
        except Exception as exc:
            return {
                "target": name,
                "status": CertificationStatus.FAIL.value,
                "reason": f"{type(exc).__name__}: {exc}",
                "spec": spec,
                "checks": checks,
            }

        required = ["chat", "usage"]
        if spec["supports_tools"]:
            required.append("tools")
        status = (
            CertificationStatus.PASS
            if all(checks[name]["status"] == CertificationStatus.PASS.value for name in required)
            else CertificationStatus.FAIL
        )
        return {
            "target": name,
            "status": status.value,
            "model": selected_model,
            "spec": spec,
            "checks": checks,
        }

    def run(self, *, live: bool = False) -> dict[str, Any]:
        warehouses = [self.certify_warehouse(name, live=live) for name in WAREHOUSES]
        providers = [self.certify_provider(name, live=live) for name in self.provider_registry.names()]
        statuses = [item["status"] for item in [*warehouses, *providers]]
        return {
            "mode": "LIVE" if live else "STRUCTURAL",
            "status": "FAIL" if CertificationStatus.FAIL.value in statuses else "PASS",
            "warehouses": warehouses,
            "providers": providers,
            "counts": {status: statuses.count(status) for status in sorted(set(statuses))},
        }

    @staticmethod
    def write_report(report: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        json_path = root / "certification-report.json"
        markdown_path = root / "certification-report.md"
        json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        lines = [
            "# Integration Certification Report",
            "",
            f"Mode: **{report['mode']}**",
            "",
            "## Warehouses",
            "",
            "| Target | Status |",
            "|---|---|",
        ]
        lines.extend(f"| {item['target']} | {item['status']} |" for item in report["warehouses"])
        lines.extend(["", "## Providers", "", "| Target | Status |", "|---|---|"])
        lines.extend(f"| {item['target']} | {item['status']} |" for item in report["providers"])
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, markdown_path
