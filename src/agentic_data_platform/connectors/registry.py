from __future__ import annotations

from agentic_data_platform.connectors.base import DataPlatformConnector


class ConnectorRegistry:
    """Explicit connector registration; no ambient SDK or credential discovery."""

    def __init__(self) -> None:
        self._connectors: dict[str, DataPlatformConnector] = {}

    def register(self, name: str, connector: DataPlatformConnector) -> None:
        if name in self._connectors:
            raise ValueError(f"connector already registered: {name}")
        self._connectors[name] = connector

    def get(self, name: str) -> DataPlatformConnector:
        try:
            return self._connectors[name]
        except KeyError as exc:
            raise KeyError(f"unknown connector: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._connectors))
