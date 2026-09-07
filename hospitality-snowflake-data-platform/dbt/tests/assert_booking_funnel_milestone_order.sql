select *
from {{ ref('fact_booking_funnel') }}
where (first_booking_attempt_at is not null and first_booking_attempt_at < funnel_started_at)
   or (first_confirmation_at is not null and first_booking_attempt_at is null)
   or (first_confirmation_at is not null and first_confirmation_at < first_booking_attempt_at)
