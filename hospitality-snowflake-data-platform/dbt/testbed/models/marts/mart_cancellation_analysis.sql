select r.hotel_id, to_date(c.cancelled_at) as cancellation_date, c.reason, c._generation_id,
       count(*) as cancellations, sum(c.fee_amount) as cancellation_fees,
       sum(r.total_amount) as cancelled_booking_value
from {{ ref('stg_cancellations') }} c
join {{ ref('fact_reservation') }} r using (reservation_id, _generation_id)
group by r.hotel_id, to_date(c.cancelled_at), c.reason, c._generation_id
