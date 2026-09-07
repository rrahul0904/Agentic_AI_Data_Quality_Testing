# Verification

Verification remains fail-closed. The Wave 1 ordered gate engine is retained and now has a pluggable AST summary for table dependencies, CTEs, joins, columns, statement types, DDL and DML classification. The fallback parser is always available; `sqlglot` is optional.

`DROP DATABASE`, `DROP SCHEMA`, and `TRUNCATE` remain hard-denied. Read-only connectors reject all mutation statements before sending them to a platform.
