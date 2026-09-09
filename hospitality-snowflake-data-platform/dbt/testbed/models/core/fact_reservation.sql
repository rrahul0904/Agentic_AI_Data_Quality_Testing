{{ config(materialized='incremental', unique_key=['reservation_id', '_generation_id'], incremental_strategy='merge', incremental_predicates=["DBT_INTERNAL_DEST._INGESTED_AT > dateadd(day, -14, current_timestamp())"], on_schema_change='sync_all_columns') }}
select reservation_id, hotel_id, guest_id, room_id, channel_id, booking_status, booked_at,
       checkin_date, checkout_date, adults, children, currency, total_amount, updated_at,
       datediff(day, checkin_date, checkout_date) as booked_nights,
       _load_id, _generation_id, _source_file, _ingested_at
from {{ ref('stg_reservations') }}
{% if is_incremental() %}
where _ingested_at >= (select dateadd(day, -2, coalesce(max(_ingested_at), '1900-01-01'::timestamp_ltz)) from {{ this }})
{% endif %}
