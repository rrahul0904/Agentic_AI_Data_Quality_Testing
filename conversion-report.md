# ShiftForge Conversion Report

- Project: `/mnt/data/shiftforge/examples/revinate`
- Models discovered: **2**
- Models converted: **2**
- Models with warnings: **0**
- Models with errors: **0**

## models/account_hierarchy.sql

Status: **converted**

Sort keys: `account_country`

- **RS_SORTKEY_001** [info] Added missing Redshift sort key 'account_country' to the SELECT list using an explicit hint.

## models/account_primary.sql

Status: **converted**

Sort keys: `account_country`

- **BQ004** [info] Normalized IFNULL to COALESCE.
- **RS_SORTKEY_001** [info] Added missing Redshift sort key 'account_country' to the SELECT list using an explicit hint.
