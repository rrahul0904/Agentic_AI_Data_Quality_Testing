from __future__ import annotations
from agentic_data_platform.models import ExecutionEvidenceRecord, ToolRequest
from agentic_data_platform.persistence.repositories import ControlPlaneRepository
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry

class GovernedExecutionService:
    def __init__(self, registry: ToolRegistry, repository: ControlPlaneRepository) -> None:
        self.registry = registry
        self.repository = repository

    def execute(self, run_id: str, request: ToolRequest, *, approval_scope: str = "production_mutation", dry_run: bool = False) -> dict:
        environment = request.environment.value
        approved = self.repository.has_approval(run_id, approval_scope, action="execute", environment=environment)
        result = self.registry.invoke(ToolInvocation(request=request, run_id=run_id, approved=approved, dry_run=dry_run))
        self.repository.save_execution_evidence(ExecutionEvidenceRecord(run_id, request.tool, request.operation, result))
        return result
