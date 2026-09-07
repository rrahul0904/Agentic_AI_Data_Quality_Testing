with reservations as (select * from {{ ref('stg_oracle_reservation') }}),
rooms as (select reservation_id, count(*) as rooms_booked, sum(room_rate) as room_rate_total from {{ ref('stg_oracle_reservation_room') }} group by 1)
select
  r.*,
  coalesce(rooms.rooms_booked, 0) as rooms_booked,
  datediff(day, r.check_in_date, r.check_out_date) as stay_nights,
  rooms.room_rate_total,
  r.reservation_status = 'CANCELLED' as is_cancelled
from reservations r
left join rooms using (reservation_id)

