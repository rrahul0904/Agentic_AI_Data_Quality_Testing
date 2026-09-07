from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"


class RuleHit(BaseModel):
    rule_id: str
    message: str
    severity: Severity = Severity.info
    line: int | None = None
    before: str | None = None
    after: str | None = None
    auto_fixed: bool = False


class ModelResult(BaseModel):
    model: str
    source_path: str
    output_path: str | None = None
    converted_sql: str
    hits: list[RuleHit] = Field(default_factory=list)
    selected_columns: list[str] = Field(default_factory=list)
    required_sort_keys: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    status: str = "converted"


class ProjectReport(BaseModel):
    project_root: str
    source_dialect: str = "bigquery"
    target_dialect: str = "redshift"
    models_discovered: int
    models_converted: int
    models_with_warnings: int
    models_with_errors: int
    results: list[ModelResult]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConvertRequest(BaseModel):
    sql: str
    model_name: str = "model.sql"
    hints: dict[str, str] = Field(default_factory=dict)
