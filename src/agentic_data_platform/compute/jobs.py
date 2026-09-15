"""Portable, approval-bound container and GPU job planning.

The planner produces inspectable backend-specific execution plans. Execution remains
explicit: Docker/Kubernetes use local CLIs and Snowflake uses a governed connector.
No backend is reported as live-certified merely because a plan can be rendered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence

import yaml

from agentic_data_platform.connectors.base import DataPlatformConnector


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,511}$")
RunFactory = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ComputeJobSpec:
    name: str
    image: str
    command: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    cpu: float = 1.0
    memory_gib: float = 2.0
    gpu: int = 0
    timeout_seconds: int = 3600
    network_enabled: bool = False
    workspace: str | None = None
    replicas: int = 1

    def validate(self) -> None:
        if not _IDENTIFIER.fullmatch(self.name):
            raise ValueError("job name must be a simple identifier")
        if not _IMAGE.fullmatch(self.image):
            raise ValueError("invalid container image")
        if not 0.1 <= float(self.cpu) <= 256:
            raise ValueError("cpu must be between 0.1 and 256")
        if not 0.1 <= float(self.memory_gib) <= 4096:
            raise ValueError("memory_gib must be between 0.1 and 4096")
        if not 0 <= int(self.gpu) <= 64:
            raise ValueError("gpu must be between 0 and 64")
        if not 1 <= int(self.replicas) <= 1000:
            raise ValueError("replicas must be between 1 and 1000")
        if not 1 <= int(self.timeout_seconds) <= 7 * 24 * 3600:
            raise ValueError("timeout_seconds is out of bounds")
        for key in self.env:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)):
                raise ValueError(f"invalid environment variable name: {key}")


@dataclass(frozen=True)
class ComputeJobPlan:
    backend: str
    spec: ComputeJobSpec
    command: tuple[str, ...] = ()
    manifest: Mapping[str, Any] | None = None
    sql: str | None = None
    risk: str = "mutating"
    requires_approval: bool = True
    estimated_resources: Mapping[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        payload = {
            "backend": self.backend,
            "spec": {
                "name": self.spec.name,
                "image": self.spec.image,
                "command": list(self.spec.command),
                "env": dict(self.spec.env),
                "cpu": self.spec.cpu,
                "memory_gib": self.spec.memory_gib,
                "gpu": self.spec.gpu,
                "timeout_seconds": self.spec.timeout_seconds,
                "network_enabled": self.spec.network_enabled,
                "workspace": self.spec.workspace,
                "replicas": self.spec.replicas,
            },
            "command": list(self.command),
            "manifest": self.manifest,
            "sql": self.sql,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "name": self.spec.name,
            "image": self.spec.image,
            "command": list(self.command),
            "manifest": self.manifest,
            "sql": self.sql,
            "risk": self.risk,
            "requires_approval": self.requires_approval,
            "estimated_resources": dict(self.estimated_resources),
            "fingerprint": self.fingerprint,
        }


class PortableComputePlanner:
    @staticmethod
    def _resources(spec: ComputeJobSpec) -> dict[str, Any]:
        return {
            "cpu": float(spec.cpu),
            "memory_gib": float(spec.memory_gib),
            "gpu": int(spec.gpu),
            "replicas": int(spec.replicas),
            "timeout_seconds": int(spec.timeout_seconds),
            "network_enabled": bool(spec.network_enabled),
        }

    def docker(self, spec: ComputeJobSpec) -> ComputeJobPlan:
        spec.validate()
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            f"ade-{spec.name.lower()}",
            "--cpus",
            str(float(spec.cpu)),
            "--memory",
            f"{float(spec.memory_gib):g}g",
        ]
        if not spec.network_enabled:
            command += ["--network", "none"]
        if spec.gpu:
            command += ["--gpus", str(int(spec.gpu))]
        for key, value in sorted(spec.env.items()):
            command += ["-e", f"{key}={value}"]
        if spec.workspace:
            workspace = Path(spec.workspace).expanduser().resolve()
            command += ["-v", f"{workspace}:/workspace:rw", "-w", "/workspace"]
        command.append(spec.image)
        command.extend(spec.command)
        return ComputeJobPlan(
            backend="docker",
            spec=spec,
            command=tuple(command),
            estimated_resources=self._resources(spec),
        )

    def kubernetes(self, spec: ComputeJobSpec, *, namespace: str = "default") -> ComputeJobPlan:
        spec.validate()
        if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", namespace):
            raise ValueError("invalid Kubernetes namespace")
        resources: dict[str, Any] = {
            "requests": {"cpu": str(spec.cpu), "memory": f"{spec.memory_gib:g}Gi"},
            "limits": {"cpu": str(spec.cpu), "memory": f"{spec.memory_gib:g}Gi"},
        }
        if spec.gpu:
            resources["limits"]["nvidia.com/gpu"] = int(spec.gpu)
        container: dict[str, Any] = {
            "name": "main",
            "image": spec.image,
            "resources": resources,
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": False,
                "runAsNonRoot": True,
                "capabilities": {"drop": ["ALL"]},
            },
            "env": [{"name": key, "value": value} for key, value in sorted(spec.env.items())],
        }
        if spec.command:
            container["command"] = [spec.command[0]]
            if len(spec.command) > 1:
                container["args"] = list(spec.command[1:])
        pod_spec: dict[str, Any] = {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "containers": [container],
        }
        manifest = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": f"ade-{spec.name.lower()}", "namespace": namespace},
            "spec": {
                "backoffLimit": 0,
                "parallelism": int(spec.replicas),
                "completions": int(spec.replicas),
                "activeDeadlineSeconds": int(spec.timeout_seconds),
                "template": {"metadata": {"labels": {"app.kubernetes.io/managed-by": "ade"}}, "spec": pod_spec},
            },
        }
        return ComputeJobPlan(
            backend="kubernetes",
            spec=spec,
            manifest=manifest,
            command=("kubectl", "apply", "-f", "-"),
            estimated_resources=self._resources(spec),
        )

    @staticmethod
    def _sf_identifier(value: str, label: str) -> str:
        parts = value.split(".")
        if not 1 <= len(parts) <= 3 or not all(_IDENTIFIER.fullmatch(part) for part in parts):
            raise ValueError(f"invalid Snowflake {label}")
        return ".".join(parts)

    def snowflake_spcs(
        self,
        spec: ComputeJobSpec,
        *,
        compute_pool: str,
        job_name: str | None = None,
        query_warehouse: str | None = None,
        external_access_integrations: Sequence[str] = (),
        async_: bool = True,
    ) -> ComputeJobPlan:
        spec.validate()
        pool = self._sf_identifier(compute_pool, "compute pool")
        name = self._sf_identifier(job_name or spec.name, "job name")
        warehouse = self._sf_identifier(query_warehouse, "warehouse") if query_warehouse else None
        integrations = [self._sf_identifier(item, "external access integration") for item in external_access_integrations]
        if integrations and not spec.network_enabled:
            raise ValueError("external access integrations require network_enabled=True")

        container: dict[str, Any] = {
            "name": "main",
            "image": spec.image,
            "env": dict(spec.env),
        }
        if spec.command:
            container["args"] = list(spec.command)
        resources: dict[str, str] = {
            "requests": {"cpu": str(spec.cpu), "memory": f"{spec.memory_gib:g}Gi"}
        }
        if spec.gpu:
            resources["requests"]["nvidia.com/gpu"] = str(int(spec.gpu))
        container["resources"] = resources
        specification = yaml.safe_dump({"spec": {"containers": [container]}}, sort_keys=False).strip()
        clauses = [
            "EXECUTE JOB SERVICE",
            f"IN COMPUTE POOL {pool}",
            f"NAME = {name}",
            f"ASYNC = {'TRUE' if async_ else 'FALSE'}",
            f"REPLICAS = {int(spec.replicas)}",
        ]
        if warehouse:
            clauses.append(f"QUERY_WAREHOUSE = {warehouse}")
        if integrations:
            clauses.append("EXTERNAL_ACCESS_INTEGRATIONS = (" + ", ".join(integrations) + ")")
        clauses.append(f"FROM SPECIFICATION $$\n{specification}\n$$")
        sql = "\n  ".join(clauses) + ";"
        return ComputeJobPlan(
            backend="snowflake_spcs",
            spec=spec,
            sql=sql,
            estimated_resources={**self._resources(spec), "compute_pool": pool},
        )


class PortableComputeRunner:
    def __init__(
        self,
        *,
        subprocess_runner: RunFactory | None = None,
        snowflake_connector: DataPlatformConnector | None = None,
    ) -> None:
        self._run = subprocess_runner or subprocess.run
        self.snowflake_connector = snowflake_connector

    def execute(self, plan: ComputeJobPlan, *, approved: bool = False) -> dict[str, Any]:
        if plan.requires_approval and not approved:
            return {
                "status": "APPROVAL_REQUIRED",
                "backend": plan.backend,
                "fingerprint": plan.fingerprint,
            }
        if plan.backend == "snowflake_spcs":
            if self.snowflake_connector is None:
                return {
                    "status": "BLOCKED_EXTERNAL",
                    "backend": plan.backend,
                    "fingerprint": plan.fingerprint,
                    "reason": "Snowflake connector is not configured",
                }
            if getattr(self.snowflake_connector, "platform", "").casefold() != "snowflake":
                raise ValueError("snowflake_spcs plan requires a Snowflake connector")
            if not plan.sql:
                raise ValueError("Snowflake compute plan is missing SQL")
            result = self.snowflake_connector.execute_governed_mutation(plan.sql)  # type: ignore[attr-defined]
            return {
                "status": "PASS",
                "backend": plan.backend,
                "fingerprint": plan.fingerprint,
                "query_id": getattr(result, "query_id", None),
                "metadata": getattr(result, "metadata", {}),
            }

        stdin = None
        if plan.backend == "kubernetes":
            stdin = yaml.safe_dump(dict(plan.manifest or {}), sort_keys=False)
        try:
            result = self._run(
                list(plan.command),
                input=stdin,
                text=True,
                capture_output=True,
                timeout=max(1, min(plan.spec.timeout_seconds, 7 * 24 * 3600)),
                check=False,
            )
        except FileNotFoundError:
            return {
                "status": "SKIP_EXTERNAL",
                "backend": plan.backend,
                "fingerprint": plan.fingerprint,
                "reason": f"{plan.command[0]} is not installed",
            }
        return {
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "backend": plan.backend,
            "fingerprint": plan.fingerprint,
            "returncode": int(result.returncode),
            "stdout": result.stdout[-200_000:],
            "stderr": result.stderr[-20_000:],
        }
