with source as ({{ stage_raw_entity('oracle', 'LOYALTY_TRANSACTION') }})
select coalesce(raw_payload:LOYALTY_TRANSACTION_ID::varchar, source_primary_key) as loyalty_transaction_id,
       raw_payload:LOYALTY_ACCOUNT_ID::varchar as loyalty_account_id, raw_payload:GUEST_ID::varchar as guest_id,
       upper(raw_payload:TRANSACTION_TYPE::varchar) as transaction_type, try_to_number(raw_payload:POINTS) as points,
       try_to_timestamp_tz(raw_payload:TRANSACTION_AT::varchar) as transaction_at, {{ audit_columns() }} from source

