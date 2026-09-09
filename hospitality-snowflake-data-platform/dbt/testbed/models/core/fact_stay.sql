{{ config(materialized='incremental', unique_key=['stay_id', '_generation_id'], incremental_strategy='merge', incremental_predicates=["DBT_INTERNAL_DEST._INGESTED_AT > dateadd(day, -14, current_timestamp())"], on_schema_change='sync_all_columns') }}
select stay_id, reservation_id, hotel_id, room_id, actual_checkin_at, actual_checkout_at, stay_status,
       datediff(minute, actual_checkin_at, actual_checkout_at) as stay_minutes,
       _load_id, _generation_id, _source_file, _ingested_at
from {{ ref('stg_stays') }}
{% if is_incremental() %}
where _ingested_at >= (select dateadd(day, -2, coalesce(max(_ingested_at), '1900-01-01'::timestamp_ltz)) from {{ this }})
{% endif %}
