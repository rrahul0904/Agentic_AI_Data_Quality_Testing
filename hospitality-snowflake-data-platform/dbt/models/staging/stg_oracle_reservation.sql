with source as ({{ stage_raw_entity('oracle', 'RESERVATION') }})
select
  coalesce(raw_payload:RESERVATION_ID::varchar, raw_payload:reservation_id::varchar, source_primary_key) as reservation_id,
  coalesce(raw_payload:GUEST_ID::varchar, raw_payload:guest_id::varchar) as guest_id,
  coalesce(raw_payload:PROPERTY_ID::varchar, raw_payload:property_id::varchar) as property_id,
  upper(coalesce(raw_payload:STATUS::varchar, raw_payload:status::varchar)) as reservation_status,
  try_to_date(coalesce(raw_payload:CHECK_IN_DATE::varchar, raw_payload:check_in_date::varchar)) as check_in_date,
  try_to_date(coalesce(raw_payload:CHECK_OUT_DATE::varchar, raw_payload:check_out_date::varchar)) as check_out_date,
  coalesce(raw_payload:CHANNEL_CODE::varchar, raw_payload:channel_code::varchar, 'UNKNOWN') as booking_channel,
  {{ safe_cast_number('coalesce(raw_payload:TOTAL_AMOUNT, raw_payload:total_amount)') }} as gross_booking_value,
  {{ audit_columns() }}
from source

