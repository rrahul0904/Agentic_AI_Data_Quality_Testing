with stays as (
  select guest_key, count(*) as lifetime_reservations, sum(stay_nights) as lifetime_room_nights,
         sum(gross_booking_value) as lifetime_value, count_if(is_cancelled) as cancellations,
         min(check_in_date) as first_stay_date, max(check_in_date) as latest_stay_date
  from {{ ref('fact_reservation') }} group by 1
)
select
  g.*,
  coalesce(s.lifetime_reservations, 0) as lifetime_reservations,
  coalesce(s.lifetime_room_nights, 0) as lifetime_room_nights,
  coalesce(s.lifetime_value, 0) as lifetime_value,
  coalesce(s.cancellations, 0) as cancellations,
  s.first_stay_date,
  s.latest_stay_date,
  coalesce(l.loyalty_tier, 'NON_MEMBER') as loyalty_tier,
  coalesce(l.point_balance, 0) as loyalty_points
from {{ ref('dim_guest') }} g
left join stays s using (guest_key)
left join {{ ref('dim_loyalty_member') }} l using (guest_key)

