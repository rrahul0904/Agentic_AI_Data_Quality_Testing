select
  {{ generate_surrogate_key(['property_id']) }} as property_key,
  property_id,
  property_code,
  property_name,
  property_status,
  loaded_at as updated_at
from {{ ref('stg_oracle_hotel_property') }}

