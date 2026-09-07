with reconciled_payments as (
  select * from {{ ref('int_payment_reconciliation') }}
),
refunds as (
  select
    payment_transaction_id,
    sum(case when refund_status in ('COMPLETED', 'REFUNDED', 'SUCCESS') then refund_amount else 0 end)
      as completed_refund_amount,
    sum(refund_amount) as requested_refund_amount,
    count(*) as refund_count,
    max(refund_at) as latest_refund_at
  from {{ ref('stg_postgres_refund_transaction') }}
  group by 1
)
select
  p.*,
  coalesce(r.completed_refund_amount, 0) as completed_refund_amount,
  coalesce(r.requested_refund_amount, 0) as requested_refund_amount,
  coalesce(r.refund_count, 0) as refund_count,
  r.latest_refund_at,
  greatest(coalesce(p.payment_amount, 0) - coalesce(r.completed_refund_amount, 0), 0)
    as net_paid_amount,
  case
    when p.payment_status in ('FAILED', 'DECLINED', 'VOIDED') then 'FAILED'
    when coalesce(r.completed_refund_amount, 0) >= coalesce(p.payment_amount, 0)
      and coalesce(p.payment_amount, 0) > 0 then 'FULLY_REFUNDED'
    when coalesce(r.completed_refund_amount, 0) > 0 then 'PARTIALLY_REFUNDED'
    when p.is_settled then 'SETTLED'
    when p.payment_status in ('COMPLETED', 'CAPTURED', 'SUCCESS') then 'CAPTURED'
    else 'PENDING'
  end as payment_lifecycle_status
from reconciled_payments p
left join refunds r using (payment_transaction_id)
