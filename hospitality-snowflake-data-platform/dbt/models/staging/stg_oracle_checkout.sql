with source as ({{ stage_raw_entity('oracle', 'CHECKOUT') }})
select coalesce(raw_payload:CHECKOUT_ID::varchar, source_primary_key) as checkout_id,
       raw_payload:RESERVATION_ID::varchar as reservation_id, raw_payload:GUEST_ID::varchar as guest_id,
       raw_payload:ROOM_ID::varchar as room_id, try_to_timestamp_tz(raw_payload:CHECKED_OUT_AT::varchar) as checked_out_at,
       {{ audit_columns() }} from source

