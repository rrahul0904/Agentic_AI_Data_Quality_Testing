-- Singular test: fails and returns offending rows if any order has a
-- non-positive amount. The demo seed intentionally includes one such row
-- (order_id 6) so a first run demonstrates a real, fail-closed test failure.
select order_id, amount
from {{ ref('stg_orders') }}
where amount <= 0
