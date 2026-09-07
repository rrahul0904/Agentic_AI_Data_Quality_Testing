with reservations as (
  select check_in_date as metric_date, property_key,
         count(*) as total_reservations, sum(stay_nights * rooms_booked) as room_nights_booked,
         sum(gross_booking_value) as gross_booking_value,
         sum(iff(is_cancelled, gross_booking_value, 0)) as cancelled_value,
         count_if(is_cancelled) as cancelled_reservations
  from {{ ref('fact_reservation') }} group by 1, 2
), inventory as (
  select date_day as metric_date, property_key, count(*) as available_room_nights,
         count_if(is_occupied) as occupied_room_nights
  from {{ ref('fact_room_night') }} group by 1, 2
)
select
  coalesce(r.metric_date, i.metric_date) as metric_date,
  coalesce(r.property_key, i.property_key) as property_key,
  coalesce(r.total_reservations, 0) as total_reservations,
  coalesce(r.room_nights_booked, 0) as room_nights_booked,
  coalesce(r.gross_booking_value, 0) as gross_booking_value,
  coalesce(r.gross_booking_value - r.cancelled_value, 0) as net_revenue,
  coalesce(i.occupied_room_nights / nullif(i.available_room_nights, 0), 0) as occupancy_rate,
  coalesce(r.gross_booking_value / nullif(r.room_nights_booked, 0), 0) as adr,
  coalesce(r.gross_booking_value / nullif(i.available_room_nights, 0), 0) as revpar,
  coalesce(r.cancelled_reservations / nullif(r.total_reservations, 0), 0) as cancellation_rate,
  current_timestamp() as calculated_at
from reservations r full outer join inventory i using (metric_date, property_key)

