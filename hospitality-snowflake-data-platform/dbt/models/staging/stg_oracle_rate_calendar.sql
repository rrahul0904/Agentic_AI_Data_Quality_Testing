with source as ({{ stage_raw_entity('oracle', 'ROOM_RATE_CALENDAR') }})
select
  coalesce(raw_payload:ROOM_RATE_CALENDAR_ID::varchar, source_primary_key) as rate_calendar_id,
  raw_payload:PROPERTY_ID::varchar as property_id,
  raw_payload:ROOM_TYPE_ID::varchar as room_type_id,
  try_to_date(raw_payload:STAY_DATE::varchar) as stay_date,
  {{ safe_cast_number('raw_payload:AMOUNT') }} as nightly_rate,
  coalesce(raw_payload:CURRENCY_CODE::varchar, 'USD') as currency_code,
  {{ audit_columns() }}
from source

