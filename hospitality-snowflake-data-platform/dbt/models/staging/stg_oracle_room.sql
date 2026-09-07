with source as ({{ stage_raw_entity('oracle', 'ROOM') }})
select
  coalesce(raw_payload:ROOM_ID::varchar, raw_payload:room_id::varchar, source_primary_key) as room_id,
  coalesce(raw_payload:PROPERTY_ID::varchar, raw_payload:property_id::varchar) as property_id,
  coalesce(raw_payload:ROOM_TYPE_ID::varchar, raw_payload:room_type_id::varchar) as room_type_id,
  coalesce(raw_payload:ROOM_NUMBER::varchar, raw_payload:room_number::varchar) as room_number,
  coalesce(raw_payload:STATUS::varchar, raw_payload:status::varchar) as room_status,
  {{ audit_columns() }}
from source

