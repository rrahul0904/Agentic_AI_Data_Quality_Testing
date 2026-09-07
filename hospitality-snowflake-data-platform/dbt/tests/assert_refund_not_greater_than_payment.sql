select *
from {{ ref('fact_refund') }}
where payment_amount is not null
  and refund_amount > payment_amount
