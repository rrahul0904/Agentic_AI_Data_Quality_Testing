with source as ({{ stage_raw_entity('oracle', 'ROOM_RATE_PLAN') }})
select
  coalesce(raw_payload:ROOM_RATE_PLAN_ID::varchar, source_primary_key) as rate_plan_id,
  raw_payload:PROPERTY_ID::varchar as property_id,
  raw_payload:RATE_PLAN_CODE::varchar as rate_plan_code,
  raw_payload:RATE_PLAN_NAME::varchar as rate_plan_name,
  upper(raw_payload:STATUS::varchar) as rate_plan_status,
  coalesce(try_to_timestamp_tz(raw_payload:SOURCE_UPDATED_AT::varchar), ingested_at) as updated_at,
  {{ audit_columns() }}
from source

