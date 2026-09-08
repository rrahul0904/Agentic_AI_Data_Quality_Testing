from pathlib import Path


def test_operator_console_has_required_product_surfaces():
    source = (Path(__file__).resolve().parents[1] / "apps" / "web" / "app" / "page.tsx").read_text()
    required = (
        "Overview", "Agent", "Assets", "Lineage", "SQL Intelligence", "dbt", "Airflow",
        "Data Quality", "Reconciliation", "Warehouses", "Connections", "Metadata", "Data Diff",
        "Migration", "Cost / FinOps", "Governance / PII", "PR Reviews", "Skills", "Training",
        "Providers", "MCP", "Jobs", "Traces", "Settings / Doctor",
    )
    for label in required:
        assert f'"{label}"' in source
    assert "RoadmapView title=" not in source
    assert "PARTIAL / NEXT WAVE" not in source
    assert "DomainView" in source
