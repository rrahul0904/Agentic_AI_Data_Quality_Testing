with source as ({{ stage_raw_entity('postgres', 'refund_transaction') }})
select coalesce(raw_payload:refund_transaction_id::varchar, source_primary_key) as refund_transaction_id,
       raw_payload:payment_transaction_id::varchar as payment_transaction_id, raw_payload:reservation_id::varchar as reservation_id,
       upper(raw_payload:status::varchar) as refund_status, upper(raw_payload:reason_code::varchar) as reason_code,
       {{ safe_cast_number('raw_payload:amount') }} as refund_amount, try_to_timestamp_tz(raw_payload:refund_at::varchar) as refund_at,
       {{ audit_columns() }} from source

