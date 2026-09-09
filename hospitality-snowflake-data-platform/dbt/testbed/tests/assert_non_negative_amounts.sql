select 'reservation' as source, reservation_id as record_id, total_amount as amount from {{ ref('fact_reservation') }} where total_amount < 0
union all
select 'payment', payment_id, amount from {{ ref('fact_payment') }} where amount < 0
