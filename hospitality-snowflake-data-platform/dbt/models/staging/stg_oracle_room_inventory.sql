with source as ({{ stage_raw_entity('oracle', 'ROOM_INVENTORY') }})
select coalesce(raw_payload:ROOM_INVENTORY_ID::varchar, source_primary_key) as room_inventory_id,
       raw_payload:PROPERTY_ID::varchar as property_id, raw_payload:ROOM_TYPE_ID::varchar as room_type_id,
       try_to_date(raw_payload:INVENTORY_DATE::varchar) as inventory_date,
       try_to_number(raw_payload:AVAILABLE_ROOMS) as available_rooms, {{ audit_columns() }} from source

