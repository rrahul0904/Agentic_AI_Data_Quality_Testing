from agentic_data_platform.quality.partitioning import describe_strategy


def test_partition_strategy_catalog_exposes_required_strategies():
    assert describe_strategy("numeric_range", ["id"]).warehouse_pushdown is True
    assert describe_strategy("timestamp_range", ["event_ts"]).warehouse_pushdown is True
    assert describe_strategy("lexicographic", ["customer_id"]).warehouse_pushdown is True
    assert describe_strategy("hash_bucket", ["customer_id"]).strategy == "HASH_BUCKET"
    assert describe_strategy("compound_key", ["tenant_id", "order_id"]).strategy == "COMPOUND_KEY"
