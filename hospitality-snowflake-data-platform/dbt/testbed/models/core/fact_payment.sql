{{ config(materialized='incremental', unique_key=['payment_id', '_generation_id'], incremental_strategy='merge', incremental_predicates=["DBT_INTERNAL_DEST._INGESTED_AT > dateadd(day, -14, current_timestamp())"], on_schema_change='append_new_columns') }}
select payment_id, reservation_id, payment_ts, payment_method, payment_status, amount, currency,
       _load_id, _generation_id, _source_file, _ingested_at
from {{ ref('stg_payments') }}
{% if is_incremental() %}
where _ingested_at >= (select dateadd(day, -2, coalesce(max(_ingested_at), '1900-01-01'::timestamp_ltz)) from {{ this }})
{% endif %}
