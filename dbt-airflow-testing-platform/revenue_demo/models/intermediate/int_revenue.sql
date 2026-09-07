-- Approved contract: COMPLETE and SHIPPED orders are recognized revenue;
-- cancelled orders contribute zero.
--
-- INJECTED DEFECT for the Revenue Quality Certification demo scenario:
-- this filter only recognizes COMPLETE orders, silently dropping SHIPPED
-- revenue. The fix is a one-line change (see revenue_demo/README.md):
--   where status in ('COMPLETE', 'SHIPPED')
select
    order_id,
    customer_id,
    status,
    gross_amount,
    discount,
    refund,
    gross_amount - discount - refund as net_revenue
from {{ ref('stg_orders') }}
where status = 'COMPLETE'
