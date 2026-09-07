with source as ({{ stage_raw_entity('oracle', 'RESERVATION_ROOM') }})
select
  coalesce(raw_payload:RESERVATION_ROOM_ID::varchar, raw_payload:reservation_room_id::varchar, source_primary_key) as reservation_room_id,
  coalesce(raw_payload:RESERVATION_ID::varchar, raw_payload:reservation_id::varchar) as reservation_id,
  coalesce(raw_payload:ROOM_ID::varchar, raw_payload:room_id::varchar) as room_id,
  coalesce(raw_payload:ROOM_TYPE_ID::varchar, raw_payload:room_type_id::varchar) as room_type_id,
  {{ safe_cast_number('coalesce(raw_payload:ROOM_RATE, raw_payload:room_rate)') }} as room_rate,
  {{ audit_columns() }}
from source

