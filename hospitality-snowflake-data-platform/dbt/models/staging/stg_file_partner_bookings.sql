with source as ({{ stage_raw_entity('files', 'partner_bookings.csv') }})
select
  raw_payload:partner_booking_id::varchar as partner_booking_id,
  raw_payload:partner_id::varchar as partner_id,
  raw_payload:property_id::varchar as property_id,
  upper(raw_payload:status::varchar) as booking_status,
  try_to_date(raw_payload:check_in_date::varchar) as check_in_date,
  try_to_date(raw_payload:check_out_date::varchar) as check_out_date,
  raw_payload:currency::varchar as currency_code,
  {{ safe_cast_number('raw_payload:gross_amount') }} as gross_amount,
  {{ safe_cast_number('raw_payload:commission_amount') }} as commission_amount,
  {{ audit_columns() }}
from source
