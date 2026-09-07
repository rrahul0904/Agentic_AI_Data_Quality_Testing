with source as ({{ stage_raw_entity('postgres', 'fraud_signal') }})
select coalesce(raw_payload:fraud_signal_id::varchar, source_primary_key) as fraud_signal_id,
       raw_payload:payment_transaction_id::varchar as payment_transaction_id,
       raw_payload:reservation_id::varchar as reservation_id, upper(raw_payload:signal_type::varchar) as signal_type,
       upper(raw_payload:severity::varchar) as severity, try_to_timestamp_tz(raw_payload:signal_at::varchar) as signal_at,
       {{ audit_columns() }} from source

