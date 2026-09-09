select * from {{ source('hospitality_raw', 'reservation_guests') }}
qualify row_number() over (partition by reservation_guest_id, _generation_id order by _ingested_at desc) = 1
