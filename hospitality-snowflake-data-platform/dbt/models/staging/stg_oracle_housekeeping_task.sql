with source as ({{ stage_raw_entity('oracle', 'HOUSEKEEPING_TASK') }})
select
  coalesce(raw_payload:HOUSEKEEPING_TASK_ID::varchar, source_primary_key) as housekeeping_task_id,
  raw_payload:ROOM_ID::varchar as room_id,
  upper(raw_payload:STATUS::varchar) as task_status,
  try_to_timestamp_tz(raw_payload:ASSIGNED_AT::varchar) as assigned_at,
  try_to_timestamp_tz(raw_payload:COMPLETED_AT::varchar) as completed_at,
  {{ audit_columns() }}
from source

