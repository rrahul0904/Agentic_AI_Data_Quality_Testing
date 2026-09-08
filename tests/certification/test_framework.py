from agentic_data_platform.certification import CertificationRunner
from agentic_data_platform.connectors.duckdb import DuckDBConnector


def test_missing_external_warehouse_is_skip_not_fake_pass():
    from agentic_data_platform.connectors.factory import ExternalConnectionUnavailable

    def factory(args):
        raise ExternalConnectionUnavailable("SNOWFLAKE_ACCOUNT not configured")

    result = CertificationRunner(connector_factory=factory).certify_warehouse("snowflake")
    assert result["status"] == "SKIP_EXTERNAL"
    assert "not configured" in result["reason"]


def test_duckdb_live_certification_executes_real_read():
    import duckdb

    connection = duckdb.connect(":memory:")
    try:
        runner = CertificationRunner(connector_factory=lambda args: DuckDBConnector(connection))
        result = runner.certify_warehouse("duckdb", live=True)
        assert result["status"] == "PASS"
        assert result["checks"]["query"]["status"] == "PASS"
    finally:
        connection.close()


def test_structural_provider_matrix_never_claims_live():
    result = CertificationRunner().run(live=False)
    assert result["mode"] == "STRUCTURAL"
    assert all(item["status"] == "NOT_RUN" for item in result["providers"])
