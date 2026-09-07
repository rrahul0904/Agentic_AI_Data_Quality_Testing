with source as ({{ stage_raw_entity('files', 'mobile_events.jsonl') }})
select raw_payload:event_id::varchar as event_id, raw_payload:user_id::varchar as app_user_id,
       raw_payload:device_id::varchar as device_id, lower(raw_payload:platform::varchar) as platform,
       raw_payload:app_version::varchar as app_version, raw_payload:event_name::varchar as event_name,
       try_to_timestamp_tz(raw_payload:event_timestamp::varchar) as event_timestamp, {{ audit_columns() }} from source

