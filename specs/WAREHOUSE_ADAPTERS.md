# Warehouse adapters

`DataPlatformConnector` is the existing typed read-only connector contract.
`WarehouseAdapter` adds a common facade for connect, ping, catalogs, schemas,
tables, columns, query, explain, usage, and cost. The Snowflake connector is
implemented for metadata/read-only SQL; usage and cost return honest `SKIP`
until a live account is configured.
