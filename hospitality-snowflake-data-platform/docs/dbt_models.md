# dbt model inventory

The implemented 41-model slice contains typed staging views for the highest-value Oracle, PostgreSQL, and file entities; intermediate reservation, identity, availability, funnel, payment, and housekeeping logic; conformed core dimensions/facts; and six analytics marts. `dbt ls --resource-type model` is the authoritative generated inventory.

Incremental payment, reservation, and clickstream models merge on stable surrogate keys and re-read a 72-hour window. Four snapshots preserve guest-profile, rate-plan, property, and loyalty-tier changes.

