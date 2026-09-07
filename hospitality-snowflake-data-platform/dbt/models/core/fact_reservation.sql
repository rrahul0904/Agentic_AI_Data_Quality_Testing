{{ config(materialized='incremental', unique_key='reservation_key', incremental_strategy='merge') }}
select
  {{ generate_surrogate_key(['reservation_id']) }} as reservation_key,
  reservation_id,
  {{ generate_surrogate_key(['guest_id']) }} as guest_key,
  {{ generate_surrogate_key(['property_id']) }} as property_key,
  {{ generate_surrogate_key(['booking_channel']) }} as channel_key,
  check_in_date,
  check_out_date,
  stay_nights,
  rooms_booked,
  gross_booking_value,
  reservation_status,
  is_cancelled,
  loaded_at
from {{ ref('int_reservation_lifecycle') }}
where stay_nights > 0
{% if is_incremental() %}and loaded_at >= dateadd(hour, -72, (select max(loaded_at) from {{ this }})){% endif %}

