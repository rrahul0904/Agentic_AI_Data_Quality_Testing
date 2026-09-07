from __future__ import annotations
import re
from agentic_data_platform.migration.spec import ColumnMapping, MigrationObject, MigrationSpec
from agentic_data_platform.models import Platform
from agentic_data_platform.sql.engine import analyze_sql

def _map_type(source_type: str) -> str:
    t = re.sub(r"\s+", " ", source_type.upper().strip())
    if t in {"INT", "INTEGER", "BIGINT"}: return "NUMBER(38,0)"
    if t in {"BIT", "BOOLEAN"}: return "BOOLEAN"
    if t.startswith("DATETIME2") or t in {"DATETIME", "SMALLDATETIME"}: return "TIMESTAMP_NTZ"
    if t == "DATE": return "DATE"
    if t.startswith("UNIQUEIDENTIFIER"): return "VARCHAR(36)"
    m = re.match(r"N?VARCHAR\s*\(([^)]+)\)", t)
    if m:
        size=m.group(1).strip(); return "VARCHAR" if size.upper()=="MAX" else f"VARCHAR({size})"
    if t in {"TEXT", "NTEXT"}: return "VARCHAR"
    m = re.match(r"(?:DECIMAL|NUMERIC)\s*\(([^)]+)\)", t)
    if m: return f"NUMBER({m.group(1)})"
    if t.startswith("FLOAT") or t == "REAL": return "FLOAT"
    raise ValueError(f"unsupported SQL Server type: {source_type}")

def plan_sqlserver_to_snowflake(source_ddl: str) -> MigrationSpec:
    analysis = analyze_sql(source_ddl, "sqlserver")
    if not analysis.parseable or not analysis.objects: raise ValueError("source DDL is not a supported CREATE TABLE statement: " + "; ".join(analysis.errors))
    source=analysis.objects[0]; target_name=source.name.upper(); mappings=[]; target_cols=[]
    for column in source.columns:
        target_type=_map_type(column.data_type); target_col=column.name.upper(); mappings.append(ColumnMapping(column.name,column.data_type,target_col,target_type,column.nullable)); target_cols.append(f'  "{target_col}" {target_type}{"" if column.nullable else " NOT NULL"}')
    target_ddl=f'CREATE TABLE {target_name} (\n'+",\n".join(target_cols)+"\n);"
    target_analysis=analyze_sql(target_ddl,"snowflake")
    if not target_analysis.safe or not target_analysis.parseable: raise ValueError("generated Snowflake DDL failed deterministic validation")
    obj=MigrationObject(source.name,target_name,"table",source_ddl,target_ddl,tuple(mappings),analysis.dependencies)
    return MigrationSpec(Platform.SQLSERVER,Platform.SNOWFLAKE,(obj,))
