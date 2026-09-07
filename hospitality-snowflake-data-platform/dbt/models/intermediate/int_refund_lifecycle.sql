with refunds as (
  select * from {{ ref('stg_postgres_refund_transaction') }}
),
payments as (
  select * from {{ ref('int_payment_lifecycle') }}
)
select
  r.refund_transaction_id,
  r.payment_transaction_id,
  coalesce(r.reservation_id, p.reservation_id) as reservation_id,
  r.refund_status,
  r.reason_code,
  r.refund_amount,
  r.refund_at,
  p.payment_amount,
  p.currency_code,
  p.payment_status,
  p.payment_lifecycle_status,
  r.payment_transaction_id is not null and p.payment_transaction_id is null as is_orphan_refund,
  case
    when r.refund_amount < 0 then 'INVALID_NEGATIVE_AMOUNT'
    when p.payment_transaction_id is null then 'PAYMENT_NOT_FOUND'
    when r.refund_amount > p.payment_amount then 'EXCEEDS_PAYMENT'
    when r.refund_status in ('COMPLETED', 'REFUNDED', 'SUCCESS') then 'COMPLETED'
    when r.refund_status in ('FAILED', 'DECLINED', 'REJECTED') then 'FAILED'
    else 'PENDING'
  end as refund_lifecycle_status,
  r.loaded_at
from refunds r
left join payments p using (payment_transaction_id)
