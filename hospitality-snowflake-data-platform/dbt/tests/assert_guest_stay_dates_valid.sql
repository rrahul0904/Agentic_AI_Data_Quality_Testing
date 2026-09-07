select *
from {{ ref('fact_guest_stay') }}
where checked_out_at is not null
  and (checked_out_at < checked_in_at or actual_stay_nights <= 0)
