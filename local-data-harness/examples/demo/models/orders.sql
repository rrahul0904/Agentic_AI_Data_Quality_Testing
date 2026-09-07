with base as (
  select *
  from orders o
  join customers c on o.customer_id = c.id
)
select
  base.id as order_id,
  base.email as customer_email,
  base.amount
from base
