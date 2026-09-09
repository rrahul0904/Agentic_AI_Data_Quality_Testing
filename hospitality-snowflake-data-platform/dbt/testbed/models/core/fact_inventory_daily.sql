{{ config(materialized='incremental', unique_key=['inventory_id', '_generation_id'], incremental_strategy='merge', on_schema_change='sync_all_columns') }}
select inventory_id, hotel_id, room_type_id, inventory_date, available_rooms, occupied_rooms,
       out_of_service_rooms, _load_id, _generation_id, _source_file, _ingested_at
from {{ ref('stg_room_inventory') }}
{% if is_incremental() %}
where _ingested_at >= (select dateadd(day, -2, coalesce(max(_ingested_at), '1900-01-01'::timestamp_ltz)) from {{ this }})
{% endif %}
