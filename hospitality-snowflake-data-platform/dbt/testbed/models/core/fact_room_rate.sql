{{ config(materialized='incremental', unique_key=['rate_id', '_generation_id'], incremental_strategy='merge', on_schema_change='fail') }}
select rate_id, hotel_id, room_type_id, rate_date, rate_plan, nightly_rate, currency,
       _load_id, _generation_id, _source_file, _ingested_at
from {{ ref('stg_daily_rates') }}
{% if is_incremental() %}
where _ingested_at >= (select dateadd(day, -2, coalesce(max(_ingested_at), '1900-01-01'::timestamp_ltz)) from {{ this }})
{% endif %}
