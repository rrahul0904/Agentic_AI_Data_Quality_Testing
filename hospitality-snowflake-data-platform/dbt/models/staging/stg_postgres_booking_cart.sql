with source as ({{ stage_raw_entity('postgres', 'booking_cart') }})
select coalesce(raw_payload:booking_cart_id::varchar, source_primary_key) as booking_cart_id,
       raw_payload:app_user_id::varchar as app_user_id, raw_payload:session_id::varchar as session_id,
       {{ safe_cast_number('raw_payload:cart_amount') }} as cart_amount,
       try_to_timestamp_tz(raw_payload:created_at::varchar) as cart_created_at,
       upper(raw_payload:status::varchar) as cart_status, {{ audit_columns() }} from source

