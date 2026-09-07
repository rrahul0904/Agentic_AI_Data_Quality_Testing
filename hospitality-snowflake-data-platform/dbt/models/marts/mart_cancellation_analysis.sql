with cancellation_events as (
  select
    reservation_id,
    min(status_changed_at) as cancelled_at
  from {{ ref('stg_oracle_reservation_status_history') }}
  where reservation_status = 'CANCELLED'
  group by 1
),
cancelled_reservations as (
  select
    r.property_key,
    r.channel_key,
    r.reservation_id,
    r.check_in_date,
    r.stay_nights,
    r.gross_booking_value,
    coalesce(to_date(c.cancelled_at), r.check_in_date) as cancellation_date,
    datediff(day, coalesce(to_date(c.cancelled_at), r.check_in_date), r.check_in_date)
      as days_before_arrival
  from {{ ref('fact_reservation') }} r
  left join cancellation_events c using (reservation_id)
  where r.is_cancelled
)
select
  cancellation_date,
  property_key,
  channel_key,
  case
    when days_before_arrival < 0 then 'AFTER_ARRIVAL'
    when days_before_arrival <= 1 then '0_TO_1_DAYS'
    when days_before_arrival <= 7 then '2_TO_7_DAYS'
    when days_before_arrival <= 30 then '8_TO_30_DAYS'
    else '31_PLUS_DAYS'
  end as cancellation_window,
  count(*) as cancelled_reservations,
  sum(stay_nights) as cancelled_room_nights,
  sum(gross_booking_value) as cancelled_booking_value,
  avg(days_before_arrival) as average_days_before_arrival
from cancelled_reservations
group by 1, 2, 3, 4
