select
  {{ generate_surrogate_key(['refund_transaction_id']) }} as refund_key,
  refund_transaction_id,
  {{ generate_surrogate_key(['payment_transaction_id']) }} as payment_key,
  {{ generate_surrogate_key(['reservation_id']) }} as reservation_key,
  payment_transaction_id,
  reservation_id,
  refund_status,
  refund_lifecycle_status,
  reason_code,
  refund_amount,
  payment_amount,
  currency_code,
  refund_at,
  is_orphan_refund,
  loaded_at
from {{ ref('int_refund_lifecycle') }}
