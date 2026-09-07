select
  date_day,
  property_key,
  count(*) as total_rooms,
  count_if(is_occupied) as occupied_rooms,
  count_if(not is_occupied) as available_rooms,
  occupied_rooms / nullif(total_rooms, 0) as occupancy_rate
from {{ ref('fact_room_night') }}
group by 1, 2

