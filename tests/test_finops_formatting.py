from __future__ import annotations

from agentic_data_platform.finops.formatting import format_bytes, truncate_query


def test_finops_format_bytes_reference_behavior():
    assert format_bytes(0) == "0 B"
    assert format_bytes(float("inf")) == "0 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(5 * 1024 * 1024) == "5.00 MB"
    assert format_bytes(-1024) == "-1.00 KB"


def test_finops_truncate_query_reference_behavior():
    assert truncate_query("", 100) == "(empty)"
    assert truncate_query("   \n  ", 100) == "(empty)"
    assert truncate_query("SELECT\n  *   FROM orders", 100) == "SELECT * FROM orders"
    assert truncate_query("abcdef", 0) == ""
    assert truncate_query("abcdef", 3) == "abc"
    assert truncate_query("SELECT something long", 10) == "SELECT ..."
