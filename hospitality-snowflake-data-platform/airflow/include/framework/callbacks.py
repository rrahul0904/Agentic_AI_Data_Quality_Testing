"""Airflow callbacks kept separate from persistence implementation."""

from .audit import record_pipeline_error

__all__ = ["record_pipeline_error"]
