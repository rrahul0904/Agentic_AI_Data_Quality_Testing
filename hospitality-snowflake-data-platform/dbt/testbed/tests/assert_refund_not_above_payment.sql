select * from {{ ref('mart_payment_reconciliation') }} where refund_amount > gross_payment_amount
