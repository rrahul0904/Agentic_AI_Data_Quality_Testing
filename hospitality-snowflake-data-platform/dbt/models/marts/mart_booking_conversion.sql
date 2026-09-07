select
  to_date(funnel_started_at) as metric_date,
  count(*) as sessions,
  sum(searches) as searches,
  sum(digital_events) as digital_events,
  count_if(reached_checkout) as checkout_sessions,
  count_if(attempted_booking) as booking_attempt_sessions,
  count_if(confirmed_booking) as confirmed_booking_sessions,
  checkout_sessions / nullif(sessions, 0) as checkout_conversion_rate,
  booking_attempt_sessions / nullif(sessions, 0) as booking_attempt_conversion_rate,
  confirmed_booking_sessions / nullif(sessions, 0) as confirmed_booking_conversion_rate
from {{ ref('int_booking_funnel') }}
where funnel_started_at is not null
group by 1
