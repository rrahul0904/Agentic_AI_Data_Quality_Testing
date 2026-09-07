select
    sum(net_revenue) as net_revenue,
    sum(gross_amount) as gross_revenue,
    count(*) as order_count
from {{ ref('int_revenue') }}
