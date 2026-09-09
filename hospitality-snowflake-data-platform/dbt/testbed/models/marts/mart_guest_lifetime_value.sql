select g.guest_id, g._generation_id, count(distinct r.reservation_id) as reservation_count,
       sum(r.total_amount) as lifetime_booking_value, max(r.checkout_date) as last_checkout_date
from {{ ref('dim_guest') }} g
left join {{ ref('fact_reservation') }} r using (guest_id, _generation_id)
group by g.guest_id, g._generation_id
