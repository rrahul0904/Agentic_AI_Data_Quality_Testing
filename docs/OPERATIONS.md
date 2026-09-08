# Operations

Primary commands are `make verify`, `make parity`, `make airflow-parity`, `make benchmark-lineage`, `make benchmark-airflow`, `make demo-smoke` and `make test-ui`.

CI additionally runs Python 3.11/3.12, dbt, Airflow-3 semantic fixtures, providers, integration, hospitality, ShiftForge, frontend, fresh-clone and exact parity gates. External credentials are not mandatory.


## Final release audit

Run `make final-audit` to execute the deterministic high-signal secret scan and user-facing release-debt scan. The security audit fails on private keys, credential URLs, common live token/key formats, and production literal secret assignments. Generic TODO/FIXME/HACK/stub markers are counted for classification but do not fail the release unless they surface as user-facing release placeholders.
