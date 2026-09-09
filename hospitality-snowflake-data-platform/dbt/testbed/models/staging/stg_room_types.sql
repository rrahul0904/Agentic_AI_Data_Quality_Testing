select * from {{ source('hospitality_raw', 'room_types') }}
qualify row_number() over (partition by room_type_id, _generation_id order by _ingested_at desc) = 1
