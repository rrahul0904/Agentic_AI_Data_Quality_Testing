select * from {{ source('hospitality_raw', 'rooms') }}
qualify row_number() over (partition by room_id, _generation_id order by _ingested_at desc) = 1
