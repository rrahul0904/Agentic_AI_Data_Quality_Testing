{{ config(materialized='incremental', unique_key=['reconciliation_date', 'currency_code'], incremental_strategy='merge') }}
select
  coalesce(settlement_date, to_date(updated_at)) as reconciliation_date,
  currency_code,
  count(*) as payment_count,
  count_if(is_settled) as settled_payment_count,
  sum(payment_amount) as processor_payment_amount,
  sum(settled_gross_amount) as settled_gross_amount,
  sum(fee_amount) as processing_fees,
  sum(settled_net_amount) as settled_net_amount,
  sum(gross_variance) as unreconciled_variance
from {{ ref('int_payment_reconciliation') }}
{% if is_incremental() %}
where updated_at >= dateadd(day, -3, (select coalesce(max(reconciliation_date), '1900-01-01'::date) from {{ this }}))
{% endif %}
group by 1, 2

