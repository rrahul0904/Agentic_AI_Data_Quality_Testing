with source as ({{ stage_raw_entity('postgres', 'support_ticket') }})
select coalesce(raw_payload:support_ticket_id::varchar, source_primary_key) as support_ticket_id,
       raw_payload:app_user_id::varchar as app_user_id, raw_payload:reservation_id::varchar as reservation_id,
       upper(raw_payload:category::varchar) as ticket_category, upper(raw_payload:status::varchar) as ticket_status,
       try_to_timestamp_tz(raw_payload:opened_at::varchar) as opened_at,
       try_to_timestamp_tz(raw_payload:resolved_at::varchar) as resolved_at, {{ audit_columns() }} from source

