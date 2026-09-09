select * from {{ source('hospitality_raw', 'guests') }}
qualify row_number() over (partition by guest_id, _generation_id order by _ingested_at desc) = 1
