select * from {{ ref('fact_reservation') }} where checkout_date < checkin_date
