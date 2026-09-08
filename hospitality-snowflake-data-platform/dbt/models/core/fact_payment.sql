{{ config(materialized='incremental', unique_key='payment_key', incremental_strategy='merge') }}
select
  {{ generate_surrogate_key(['payment_transaction_id']) }} as payment_key,
  payment_transaction_id,
  {{ generate_surrogate_key(['reservation_id']) }} as reservation_key,
  payment_status,
  payment_amount,
  currency_code,
  is_settled,
  settled_gross_amount,
  fee_amount,
  settled_net_amount,
  gross_variance,
  completed_refund_amount,
  requested_refund_amount,
  refund_count,
  latest_refund_at,
  net_paid_amount,
  payment_lifecycle_status,
  loaded_at
from {{ ref('int_payment_lifecycle') }}
{% if is_incremental() %}
qualify loaded_at >= dateadd(hour, -72, (select coalesce(max(loaded_at), '1900-01-01'::timestamp) from {{ this }}))
{% endif %}
