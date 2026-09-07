with source as ({{ stage_raw_entity('oracle', 'RESTAURANT_RESERVATION') }})
select coalesce(raw_payload:RESTAURANT_RESERVATION_ID::varchar, source_primary_key) as restaurant_reservation_id,
       raw_payload:PROPERTY_ID::varchar as property_id, raw_payload:GUEST_ID::varchar as guest_id,
       raw_payload:RESERVATION_ID::varchar as reservation_id, try_to_date(raw_payload:SERVICE_DATE::varchar) as service_date,
       try_to_number(raw_payload:PARTY_SIZE) as party_size, {{ safe_cast_number('raw_payload:AMOUNT') }} as booking_amount,
       upper(raw_payload:STATUS::varchar) as booking_status, {{ audit_columns() }} from source

