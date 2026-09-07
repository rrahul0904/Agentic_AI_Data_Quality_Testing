with source as ({{ stage_raw_entity('postgres', 'booking_attempt') }})
select coalesce(raw_payload:booking_attempt_id::varchar, source_primary_key) as booking_attempt_id,
       raw_payload:booking_cart_id::varchar as booking_cart_id, raw_payload:session_id::varchar as session_id,
       upper(raw_payload:status::varchar) as attempt_status, {{ safe_cast_number('raw_payload:amount') }} as attempt_amount,
       try_to_timestamp_tz(raw_payload:attempted_at::varchar) as attempted_at, {{ audit_columns() }} from source

