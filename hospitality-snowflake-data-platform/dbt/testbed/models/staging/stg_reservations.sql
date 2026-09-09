select * from {{ source('hospitality_raw', 'reservations') }}
qualify row_number() over (partition by reservation_id, _generation_id order by updated_at desc, _ingested_at desc) = 1
