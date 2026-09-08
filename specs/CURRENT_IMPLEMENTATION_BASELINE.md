# Current Implementation Baseline

Captured before this implementation wave on `altimate-full-parity` at `94dc6ef55907bcb089845c9678d82aeb35571871`.

- Python CI: 3.11 / 3.12
- Node CI: 22
- dbt dev target: dbt-snowflake >=1.9,<2
- Airflow runtime: optional; static DAG analysis does not import Airflow
- Registered deterministic tools: **285**
- API routes: **117**
- Provider adapters/configurations: **17**
- Built-in skills: **21**
- Warehouse targets surfaced: **12**
- Hospitality proving ground: **55 Airflow DAGs**, **70 dbt models**
- Test files: **46**

Pinned Altimate reference refreshed to `ec475f46ba0a4ce6bcfbed33cebacf31ad45a455`.

This baseline intentionally records the pre-change head so later evidence can distinguish existing behavior from this implementation wave.
