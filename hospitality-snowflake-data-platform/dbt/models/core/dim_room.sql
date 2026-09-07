select
  {{ generate_surrogate_key(['room_id']) }} as room_key,
  {{ generate_surrogate_key(['property_id']) }} as property_key,
  room_id,
  property_id,
  room_type_id,
  room_number,
  room_status,
  loaded_at as updated_at
from {{ ref('stg_oracle_room') }}

