select
  {{ generate_surrogate_key(['room_id', 'date_day']) }} as room_night_key,
  {{ generate_surrogate_key(['property_id']) }} as property_key,
  {{ generate_surrogate_key(['room_id']) }} as room_key,
  to_number(to_char(date_day, 'YYYYMMDD')) as date_key,
  date_day,
  is_occupied,
  1 as available_room_nights
from {{ ref('int_room_availability_daily') }}

