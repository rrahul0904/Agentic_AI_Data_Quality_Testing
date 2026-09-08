# Agentic Failure Scenario Library

The proving ground contains 18 regression scenarios:

1. watermark advanced beyond extract
2. dbt filter excludes valid status
3. join fanout
4. incremental late-arriving-data predicate defect
5. duplicate Airflow retry load
6. Snowflake permission failure
7. partial manifest/load
8. source schema drift
9. freshness breach
10. null-rate spike
11. revenue reconciliation mismatch
12. referential-integrity failure
13. CDC event loss
14. out-of-order event
15. dbt test failure
16. dbt compilation failure
17. Airflow task failure
18. Airflow green + dbt green + business data bad

Ground-truth labels are benchmark assertions only; they are excluded from `FailureScenario.agent_context()`.

Run `make test-agentic`, `make benchmark-agentic`, and `make demo-agentic`.
