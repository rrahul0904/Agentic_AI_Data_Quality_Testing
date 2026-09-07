with checkins as (
  select
    reservation_id,
    min(checked_in_at) as checked_in_at,
    min_by(guest_id, checked_in_at) as checked_in_guest_id,
    min_by(room_id, checked_in_at) as checked_in_room_id,
    max(loaded_at) as checkin_loaded_at
  from {{ ref('stg_oracle_checkin') }}
  where reservation_id is not null
  group by 1
),
checkouts as (
  select
    reservation_id,
    max(checked_out_at) as checked_out_at,
    max(loaded_at) as checkout_loaded_at
  from {{ ref('stg_oracle_checkout') }}
  where reservation_id is not null
  group by 1
),
primary_rooms as (
  select reservation_id, min(room_id) as room_id
  from {{ ref('stg_oracle_reservation_room') }}
  group by 1
),
folios as (
  select reservation_id, sum(folio_amount) as folio_amount, max(loaded_at) as folio_loaded_at
  from {{ ref('stg_oracle_folio') }}
  group by 1
)
select
  {{ generate_surrogate_key(['r.reservation_id']) }} as guest_stay_key,
  {{ generate_surrogate_key(['r.reservation_id']) }} as reservation_key,
  {{ generate_surrogate_key(['coalesce(c.checked_in_guest_id, r.guest_id)']) }} as guest_key,
  {{ generate_surrogate_key(['r.property_id']) }} as property_key,
  {{ generate_surrogate_key(['coalesce(c.checked_in_room_id, pr.room_id)']) }} as room_key,
  r.reservation_id,
  coalesce(c.checked_in_guest_id, r.guest_id) as guest_id,
  r.property_id,
  coalesce(c.checked_in_room_id, pr.room_id) as room_id,
  r.check_in_date as planned_check_in_date,
  r.check_out_date as planned_check_out_date,
  c.checked_in_at,
  o.checked_out_at,
  datediff(day, to_date(c.checked_in_at), to_date(o.checked_out_at)) as actual_stay_nights,
  f.folio_amount,
  o.checked_out_at is not null as is_completed_stay,
  greatest_ignore_nulls(r.loaded_at, c.checkin_loaded_at, o.checkout_loaded_at, f.folio_loaded_at) as loaded_at
from {{ ref('int_reservation_lifecycle') }} r
join checkins c using (reservation_id)
left join checkouts o using (reservation_id)
left join primary_rooms pr using (reservation_id)
left join folios f using (reservation_id)
