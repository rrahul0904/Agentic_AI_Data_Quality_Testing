{{ config(materialized='incremental', unique_key=['folio_id', '_generation_id'], incremental_strategy='merge', on_schema_change='sync_all_columns') }}
select folio_id, reservation_id, charge_ts, charge_type, description, amount, currency,
       _load_id, _generation_id, _source_file, _ingested_at
from {{ ref('stg_folio_charges') }}
{% if is_incremental() %}
where _ingested_at >= (select dateadd(day, -2, coalesce(max(_ingested_at), '1900-01-01'::timestamp_ltz)) from {{ this }})
{% endif %}
