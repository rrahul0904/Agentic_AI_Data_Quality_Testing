{{ config(materialized='incremental', unique_key='payment_transaction_id', incremental_strategy='merge') }}
with source as ({{ stage_raw_entity('postgres', 'payment_transaction') }})
select
  coalesce(raw_payload:payment_transaction_id::varchar, source_primary_key) as payment_transaction_id,
  raw_payload:reservation_id::varchar as reservation_id,
  upper(raw_payload:status::varchar) as payment_status,
  {{ safe_cast_number('raw_payload:amount') }} as payment_amount,
  coalesce(raw_payload:currency_code::varchar, 'USD') as currency_code,
  try_to_timestamp_tz(raw_payload:source_updated_at::varchar) as updated_at,
  {{ audit_columns() }}
from source
{% if is_incremental() %}
where ingested_at >= dateadd(hour, -{{ var('raw_lookback_hours') }}, (select max(loaded_at) from {{ this }}))
{% endif %}

