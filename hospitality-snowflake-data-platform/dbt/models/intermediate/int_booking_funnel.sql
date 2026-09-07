with searches as (
  select
    session_id,
    min_by(app_user_id, searched_at) as app_user_id,
    min_by(property_id, searched_at) as property_id,
    min(searched_at) as first_search_at,
    count(*) as searches,
    max(loaded_at) as search_loaded_at
  from {{ ref('stg_postgres_search_request') }}
  where session_id is not null
  group by 1
),
clicks as (
  select
    session_id,
    min_by(property_id, event_timestamp) as property_id,
    min(event_timestamp) as first_event_at,
    min(case when lower(event_name) = 'checkout' then event_timestamp end) as first_checkout_at,
    count(*) as digital_events,
    count_if(lower(event_name) = 'checkout') as checkout_events,
    max(loaded_at) as click_loaded_at
  from {{ ref('stg_file_clickstream_events') }}
  where session_id is not null
  group by 1
),
attempts as (
  select
    a.session_id,
    min(a.attempted_at) as first_booking_attempt_at,
    min(c.confirmed_at) as first_confirmation_at,
    count(distinct a.booking_attempt_id) as booking_attempts,
    count(distinct c.booking_confirmation_id) as booking_confirmations,
    greatest_ignore_nulls(max(a.loaded_at), max(c.loaded_at)) as attempt_loaded_at
  from {{ ref('stg_postgres_booking_attempt') }} a
  left join {{ ref('stg_postgres_booking_confirmation') }} c using (booking_attempt_id)
  where a.session_id is not null
  group by 1
),
sessions as (
  select session_id from searches
  union
  select session_id from clicks
  union
  select session_id from attempts
)
select
  sessions.session_id,
  s.app_user_id,
  coalesce(s.property_id, c.property_id) as property_id,
  least_ignore_nulls(s.first_search_at, c.first_event_at, a.first_booking_attempt_at) as funnel_started_at,
  c.first_checkout_at,
  a.first_booking_attempt_at,
  a.first_confirmation_at,
  coalesce(s.searches, 0) as searches,
  coalesce(c.digital_events, 0) as digital_events,
  coalesce(c.checkout_events, 0) as checkout_events,
  coalesce(a.booking_attempts, 0) as booking_attempts,
  coalesce(a.booking_confirmations, 0) as booking_confirmations,
  coalesce(c.checkout_events, 0) > 0 as reached_checkout,
  coalesce(a.booking_attempts, 0) > 0 as attempted_booking,
  coalesce(a.booking_confirmations, 0) > 0 as confirmed_booking,
  greatest_ignore_nulls(s.search_loaded_at, c.click_loaded_at, a.attempt_loaded_at) as loaded_at
from sessions
left join searches s using (session_id)
left join clicks c using (session_id)
left join attempts a using (session_id)
