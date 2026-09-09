select h.hotel_id, h.hotel_name, o.metric_date, o._generation_id, o.available_rooms, o.occupied_rooms,
       o.occupancy_pct, coalesce(r.gross_revenue, 0) as gross_revenue,
       coalesce(r.adr, 0) as adr, coalesce(r.revpar, 0) as revpar
from {{ ref('dim_hotel') }} h
join {{ ref('mart_daily_occupancy') }} o using (hotel_id, _generation_id)
left join {{ ref('mart_daily_revenue') }} r using (hotel_id, metric_date, _generation_id)
