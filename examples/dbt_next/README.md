# dbt Next example

Validate and compile the sample dashboard:

```bash
ade dbt-next chart-validate --args '{"path":"examples/dbt_next/executive_revenue.dashboard.yml"}'
ade dbt-next chart-compile --args '{"path":"examples/dbt_next/executive_revenue.dashboard.yml"}'
```

The source YAML is provider-neutral. Compilation produces contracts that downstream Power BI, Excel, web and AI adapters can consume.
