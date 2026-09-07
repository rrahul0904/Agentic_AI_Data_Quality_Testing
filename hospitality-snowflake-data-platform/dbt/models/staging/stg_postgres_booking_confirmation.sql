with source as ({{ stage_raw_entity('postgres', 'booking_confirmation') }})
select
  coalesce(raw_payload:booking_confirmation_id::varchar, source_primary_key) as booking_confirmation_id,
  raw_payload:reservation_id::varchar as reservation_id,
  raw_payload:booking_attempt_id::varchar as booking_attempt_id,
  upper(raw_payload:status::varchar) as confirmation_status,
  try_to_timestamp_tz(raw_payload:source_created_at::varchar) as confirmed_at,
  {{ audit_columns() }}
from source

