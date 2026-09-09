with payments as (
  select reservation_id, _generation_id, sum(amount) as gross_payment_amount
  from {{ ref('fact_payment') }} group by reservation_id, _generation_id
), refunds as (
  select reservation_id, _generation_id, sum(amount) as refund_amount
  from {{ ref('stg_refunds') }} group by reservation_id, _generation_id
)
select r.reservation_id, r._generation_id, r.total_amount as booking_amount,
       coalesce(p.gross_payment_amount, 0) as gross_payment_amount,
       coalesce(f.refund_amount, 0) as refund_amount,
       coalesce(p.gross_payment_amount, 0) - coalesce(f.refund_amount, 0) as net_payment_amount,
       r.total_amount - (coalesce(p.gross_payment_amount, 0) - coalesce(f.refund_amount, 0)) as outstanding_amount
from {{ ref('fact_reservation') }} r
left join payments p using (reservation_id, _generation_id)
left join refunds f using (reservation_id, _generation_id)
