"""Metadata-driven hospitality ingestion framework.

The modules are intentionally independent from DAG declaration code so they can
be exercised in local mode without starting Airflow or connecting to Snowflake.
"""

from .audit import audit_batch, record_pipeline_error
from .batch import create_batch
from .callbacks import record_pipeline_error as failure_callback
from .extractor import extract
from .landing import land
from .quality import quality_gate
from .reconciliation import reconcile
from .snowflake_loader import copy_raw, stage
from .validator import validate
from .watermark import read_watermark, update_watermark

__all__ = [
    "audit_batch",
    "copy_raw",
    "create_batch",
    "extract",
    "failure_callback",
    "land",
    "quality_gate",
    "read_watermark",
    "reconcile",
    "record_pipeline_error",
    "stage",
    "update_watermark",
    "validate",
]
