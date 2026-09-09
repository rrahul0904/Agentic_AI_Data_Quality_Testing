select r.hotel_id, to_date(f.charge_ts) as metric_date, f._generation_id,
       sum(f.amount) as gross_revenue,
       sum(iff(f.charge_type = 'ROOM', f.amount, 0)) / nullif(sum(iff(f.charge_type = 'ROOM', r.booked_nights, 0)), 0) as adr,
       sum(iff(f.charge_type = 'ROOM', f.amount, 0)) / nullif(count(distinct r.room_id), 0) as revpar
from {{ ref('fact_folio_charge') }} f
join {{ ref('fact_reservation') }} r using (reservation_id, _generation_id)
group by r.hotel_id, to_date(f.charge_ts), f._generation_id
