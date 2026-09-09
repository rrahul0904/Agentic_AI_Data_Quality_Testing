select * from {{ source('hospitality_raw', 'channel_bookings') }}
qualify row_number() over (partition by channel_booking_id, _generation_id order by booked_at desc, _ingested_at desc) = 1
