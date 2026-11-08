"""Offline demonstration: no API key, live DB, Docker, or SQL execution needed."""
import sqlite3

from agentic_data_platform.semantic.ontology_review import OntologyReviewLedger, schema_fingerprint


class DemoRegistry:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.resource = {
            "resource_id": "demo-revenue",
            "elements": [
                {"kind": "metric", "name": "net_revenue", "parent": "orders",
                 "description": "Net order revenue", "expression": "SUM(net_amount)",
                 "data_type": "NUMBER", "metadata": {"synonyms": ["net sales"]}}
            ],
            "relationships": [],
        }

    def show(self, resource_id):
        if resource_id != self.resource["resource_id"]:
            raise KeyError(resource_id)
        return self.resource


def main():
    registry = DemoRegistry()
    ledger = OntologyReviewLedger(registry)
    columns = [{"table": "orders", "column": "net_amount", "data_type": "DECIMAL"}]
    source = schema_fingerprint(columns)
    def check(concepts, signature):
        outcome = ledger.gate("demo-revenue", requested_concepts=concepts,
                              current_source_sha256=signature)
        print(f"{concepts!r}: {outcome['status']} - {outcome.get('reason', 'reviewed concept only; SQL not authorized')}")
    check(["net_revenue"], source)  # blocked until a human review receipt is recorded
    ledger.record_review("demo-revenue", kind="metric", name="net_revenue", parent="orders",
                         reviewer="offline-demo-reviewer", evidence_ref="SYNTHETIC-REVIEW-TICKET",
                         source_sha256=source)
    check(["net sales"], source)    # eligible for separate SQL validation, NOT execution
    check(["ad spend"], source)    # never invent missing business data
    newer = schema_fingerprint([{"table": "orders", "column": "net_amount", "data_type": "FLOAT"}])
    check(["net_revenue"], newer)  # blocks on source-schema change


if __name__ == "__main__":
    main()
