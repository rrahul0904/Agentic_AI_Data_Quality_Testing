select * from {{ ref('fact_stay') }} where actual_checkout_at < actual_checkin_at
