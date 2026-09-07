select p.*
from {{ ref('fact_payment') }} p
left join {{ ref('fact_reservation') }} r using (reservation_key)
where r.reservation_key is null
