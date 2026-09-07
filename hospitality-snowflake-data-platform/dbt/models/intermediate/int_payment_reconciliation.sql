with payments as (select * from {{ ref('stg_postgres_payment_transaction') }}),
settlements as (
  select payment_transaction_id, sum(gross_amount) as settled_gross_amount, sum(fee_amount) as fee_amount,
         sum(net_amount) as settled_net_amount, max(settlement_date) as settlement_date
  from {{ ref('stg_file_payment_settlements') }} group by 1
)
select
  p.*,
  s.settled_gross_amount,
  s.fee_amount,
  s.settled_net_amount,
  s.settlement_date,
  coalesce(p.payment_amount, 0) - coalesce(s.settled_gross_amount, 0) as gross_variance,
  s.payment_transaction_id is not null as is_settled
from payments p left join settlements s using (payment_transaction_id)

