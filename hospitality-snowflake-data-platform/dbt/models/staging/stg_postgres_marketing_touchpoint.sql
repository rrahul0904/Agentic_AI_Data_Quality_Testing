with source as ({{ stage_raw_entity('postgres', 'marketing_touchpoint') }})
select coalesce(raw_payload:marketing_touchpoint_id::varchar, source_primary_key) as marketing_touchpoint_id,
       raw_payload:app_user_id::varchar as app_user_id, raw_payload:session_id::varchar as session_id,
       raw_payload:marketing_campaign_id::varchar as marketing_campaign_id, upper(raw_payload:channel::varchar) as marketing_channel,
       try_to_timestamp_tz(raw_payload:touchpoint_at::varchar) as touchpoint_at,
       {{ safe_cast_number('raw_payload:cost_amount') }} as cost_amount, {{ audit_columns() }} from source

