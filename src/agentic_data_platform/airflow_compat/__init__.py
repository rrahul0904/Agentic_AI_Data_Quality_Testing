"""Airflow 2/3 compatibility, static intelligence, and governed runtime access."""

from .control import AirflowControlPlane
from .runtime import AirflowAdapter
from .evidence import availability, collection, normalize_task_instance

__all__ = ["AirflowAdapter", "AirflowControlPlane", "availability", "collection", "normalize_task_instance"]
