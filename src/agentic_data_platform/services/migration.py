from __future__ import annotations
from agentic_data_platform.migration.spec import MigrationSpec
from agentic_data_platform.migration.sqlserver_snowflake import plan_sqlserver_to_snowflake

class MigrationPlanningService:
    def plan(self, source_platform: str, target_platform: str, source_ddl: str) -> MigrationSpec:
        pair=(source_platform.lower(),target_platform.lower())
        if pair==("sqlserver","snowflake"): return plan_sqlserver_to_snowflake(source_ddl)
        raise NotImplementedError(f"migration pair not implemented: {source_platform}->{target_platform}")
