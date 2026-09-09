select * from {{ source('hospitality_raw', 'hotels') }}
qualify row_number() over (partition by hotel_id, _generation_id order by _ingested_at desc) = 1
