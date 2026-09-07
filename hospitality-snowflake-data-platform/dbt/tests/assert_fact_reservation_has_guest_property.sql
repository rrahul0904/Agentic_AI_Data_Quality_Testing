select *
from {{ ref('fact_reservation') }}
where guest_key is null
   or property_key is null
   or reservation_id is null
