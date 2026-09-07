with source as ({{ stage_raw_entity('oracle', 'RESERVATION_STATUS_HISTORY') }})
select coalesce(raw_payload:RESERVATION_STATUS_HISTORY_ID::varchar, source_primary_key) as reservation_status_history_id,
       raw_payload:RESERVATION_ID::varchar as reservation_id, upper(raw_payload:STATUS::varchar) as reservation_status,
       try_to_timestamp_tz(raw_payload:CHANGED_AT::varchar) as status_changed_at, {{ audit_columns() }} from source

