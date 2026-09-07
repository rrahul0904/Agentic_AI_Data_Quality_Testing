select *
from {{ ref('mart_cancellation_analysis') }}
where cancelled_reservations <= 0
   or cancelled_room_nights <= 0
   or cancelled_booking_value < 0
