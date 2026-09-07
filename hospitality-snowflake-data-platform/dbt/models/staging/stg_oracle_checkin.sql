with source as ({{ stage_raw_entity('oracle', 'CHECKIN') }})
select coalesce(raw_payload:CHECKIN_ID::varchar, source_primary_key) as checkin_id,
       raw_payload:RESERVATION_ID::varchar as reservation_id, raw_payload:GUEST_ID::varchar as guest_id,
       raw_payload:ROOM_ID::varchar as room_id, try_to_timestamp_tz(raw_payload:CHECKED_IN_AT::varchar) as checked_in_at,
       {{ audit_columns() }} from source

