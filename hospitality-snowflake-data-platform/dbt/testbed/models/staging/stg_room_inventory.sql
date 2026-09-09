select * from {{ source('hospitality_raw', 'room_inventory') }}
qualify row_number() over (partition by inventory_id, _generation_id order by _ingested_at desc) = 1
