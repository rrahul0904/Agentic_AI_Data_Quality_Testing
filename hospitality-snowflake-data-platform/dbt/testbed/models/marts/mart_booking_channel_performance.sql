select channel_id, _generation_id, count(*) as reservations,
       sum(total_amount) as booked_revenue,
       count_if(booking_status = 'CANCELLED') as cancellations,
       round(100.0 * count_if(booking_status = 'CANCELLED') / nullif(count(*), 0), 2) as cancellation_pct
from {{ ref('fact_reservation') }}
group by channel_id, _generation_id
