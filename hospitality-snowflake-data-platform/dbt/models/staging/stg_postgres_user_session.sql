with source as ({{ stage_raw_entity('postgres', 'user_session') }})
select coalesce(raw_payload:session_id::varchar, source_primary_key) as session_id,
       raw_payload:app_user_id::varchar as app_user_id, try_to_timestamp_tz(raw_payload:started_at::varchar) as started_at,
       try_to_timestamp_tz(raw_payload:ended_at::varchar) as ended_at, {{ audit_columns() }} from source

