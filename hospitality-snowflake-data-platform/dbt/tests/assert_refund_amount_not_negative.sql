select *
from {{ ref('fact_refund') }}
where refund_amount < 0
