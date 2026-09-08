# Airflow Intelligence

Static Airflow analysis never imports user DAG files. It parses Python AST and repository source to recover DAGs, tasks, TaskGroups, dependencies, connections, Variables, Assets/Datasets, mapping, sensors, deferrables, pools, queues, bundles, deadlines/SLAs, XCom and upgrade/security findings.

The static layer is intentionally useful without Apache Airflow installed. Airflow 3 Task SDK/Assets semantics coexist with relevant Airflow 2 Dataset/SLA compatibility diagnostics.
