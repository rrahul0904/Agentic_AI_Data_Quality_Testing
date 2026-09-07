with source as ({{ stage_raw_entity('oracle', 'MAINTENANCE_TICKET') }})
select
  coalesce(raw_payload:MAINTENANCE_TICKET_ID::varchar, source_primary_key) as maintenance_ticket_id,
  raw_payload:PROPERTY_ID::varchar as property_id,
  raw_payload:ROOM_ID::varchar as room_id,
  upper(raw_payload:STATUS::varchar) as ticket_status,
  try_to_timestamp_tz(raw_payload:OPENED_AT::varchar) as opened_at,
  try_to_timestamp_tz(raw_payload:RESOLVED_AT::varchar) as resolved_at,
  {{ audit_columns() }}
from source

