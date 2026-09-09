select r.room_id, r.hotel_id, r.room_type_id, r.room_number, r.floor_number, r.status,
       t.type_name, t.max_occupancy, t.base_rate, t.bed_type, r._generation_id, r._ingested_at
from {{ ref('stg_rooms') }} r
left join {{ ref('stg_room_types') }} t
  on r.room_type_id = t.room_type_id and r._generation_id = t._generation_id
