select
    order_id,
    customer_id,
    status,
    amount,
    cast(order_date as date) as order_date
from {{ ref('raw_orders') }}
