select
    order_id,
    customer_id,
    status,
    gross_amount,
    discount,
    refund,
    cast(order_date as date) as order_date
from {{ ref('raw_orders') }}
