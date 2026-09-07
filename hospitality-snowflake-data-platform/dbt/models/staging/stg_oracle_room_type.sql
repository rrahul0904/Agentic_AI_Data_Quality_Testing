with source as ({{ stage_raw_entity('oracle', 'ROOM_TYPE') }})
select coalesce(raw_payload:ROOM_TYPE_ID::varchar, source_primary_key) as room_type_id,
       raw_payload:PROPERTY_ID::varchar as property_id, raw_payload:ROOM_TYPE_CODE::varchar as room_type_code,
       try_to_number(raw_payload:MAX_OCCUPANCY) as max_occupancy, upper(raw_payload:STATUS::varchar) as room_type_status,
       {{ audit_columns() }} from source

