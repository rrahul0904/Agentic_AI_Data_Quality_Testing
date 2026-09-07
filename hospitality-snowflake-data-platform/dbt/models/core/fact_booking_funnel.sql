select
  {{ generate_surrogate_key(['f.session_id']) }} as booking_funnel_key,
  f.session_id,
  i.guest_key,
  {{ generate_surrogate_key(['f.property_id']) }} as property_key,
  to_number(to_char(to_date(f.funnel_started_at), 'YYYYMMDD')) as date_key,
  f.funnel_started_at,
  f.first_checkout_at,
  f.first_booking_attempt_at,
  f.first_confirmation_at,
  f.searches,
  f.digital_events,
  f.checkout_events,
  f.booking_attempts,
  f.booking_confirmations,
  f.reached_checkout,
  f.attempted_booking,
  f.confirmed_booking,
  f.loaded_at
from {{ ref('int_booking_funnel') }} f
left join {{ ref('int_guest_identity_resolution') }} i using (app_user_id)
where f.session_id is not null
