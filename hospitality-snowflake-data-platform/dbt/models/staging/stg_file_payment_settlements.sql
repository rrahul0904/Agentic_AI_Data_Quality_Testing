with source as ({{ stage_raw_entity('files', 'payment_gateway_settlements.csv') }})
select
  raw_payload:settlement_id::varchar as settlement_id,
  raw_payload:transaction_id::varchar as payment_transaction_id,
  raw_payload:gateway::varchar as gateway,
  try_to_date(raw_payload:settlement_date::varchar) as settlement_date,
  raw_payload:currency::varchar as currency_code,
  {{ safe_cast_number('raw_payload:gross_amount') }} as gross_amount,
  {{ safe_cast_number('raw_payload:fee_amount') }} as fee_amount,
  {{ safe_cast_number('raw_payload:net_amount') }} as net_amount,
  upper(raw_payload:status::varchar) as settlement_status,
  {{ audit_columns() }}
from source
