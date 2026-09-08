"""Typed, least-privilege connector capability declarations."""

from __future__ import annotations

from enum import Enum


class ConnectorCapability(str, Enum):
    LIST_CATALOGS = "list_catalogs"
    LIST_SCHEMAS = "list_schemas"
    LIST_TABLES = "list_tables"
    DESCRIBE_TABLE = "describe_table"
    QUERY_READ = "query_read"
    QUERY_DRY_RUN = "query_dry_run"
    QUERY_WRITE = "query_write"
    GET_DDL = "get_ddl"
    GET_QUERY_HISTORY = "get_query_history"
    GET_LINEAGE = "get_lineage"
    GET_METADATA_TAGS = "get_metadata_tags"
    GET_ROLE_METADATA = "get_role_metadata"
    GET_COST_METADATA = "get_cost_metadata"
