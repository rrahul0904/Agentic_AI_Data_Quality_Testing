select inventory_date as metric_date, hotel_id, _generation_id,
       sum(available_rooms) as available_rooms, sum(occupied_rooms) as occupied_rooms,
       round(100.0 * sum(occupied_rooms) / nullif(sum(available_rooms), 0), 2) as occupancy_pct
from {{ ref('fact_inventory_daily') }}
group by inventory_date, hotel_id, _generation_id
