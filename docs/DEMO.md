# Demo

`scripts/demo-full-platform.sh` is the master local acceptance demo. It bootstraps dbt artifacts/evidence and exercises the real FastAPI surface through TestClient. `scripts/demo-airflow.sh` focuses on Airflow inventory, Assets, operations, capacity, upgrades, security, bundles, failure lab and backfill planning.

The scripts label the environment LOCAL_SIMULATION and fail on broken HTTP contracts.
