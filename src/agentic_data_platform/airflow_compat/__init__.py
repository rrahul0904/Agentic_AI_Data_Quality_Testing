"""Airflow 2/3 compatibility, static intelligence, and governed runtime access."""

from .control import AirflowControlPlane
from .runtime import AirflowAdapter

__all__ = ["AirflowAdapter", "AirflowControlPlane"]
