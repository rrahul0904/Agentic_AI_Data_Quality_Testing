SELECT reconciliation_date, currency_code, payment_count, settled_payment_count, processor_payment_amount,
       settled_gross_amount, processing_fees, settled_net_amount, unreconciled_variance
FROM HOSPITALITY_DW.MART.MART_PAYMENT_RECONCILIATION
WHERE ABS(unreconciled_variance) > 0.01
ORDER BY reconciliation_date DESC;

