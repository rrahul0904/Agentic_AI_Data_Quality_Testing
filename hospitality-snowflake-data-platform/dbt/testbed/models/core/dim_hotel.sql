select hotel_id, hotel_name, brand, city, state, country, timezone, opened_date, room_count, active,
       _generation_id, _ingested_at
from {{ ref('stg_hotels') }}
