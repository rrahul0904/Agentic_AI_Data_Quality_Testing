with source as ({{ stage_raw_entity('postgres', 'guest_review') }})
select coalesce(raw_payload:guest_review_id::varchar, source_primary_key) as guest_review_id,
       raw_payload:reservation_id::varchar as reservation_id, raw_payload:guest_id::varchar as guest_id,
       raw_payload:property_id::varchar as property_id, try_to_number(raw_payload:rating) as rating,
       raw_payload:review_text::varchar as review_text, try_to_timestamp_tz(raw_payload:reviewed_at::varchar) as reviewed_at,
       upper(raw_payload:status::varchar) as review_status, {{ audit_columns() }} from source

