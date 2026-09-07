with rooms as (select * from {{ ref('stg_oracle_room') }}),
reservation_rooms as (select rr.*, r.check_in_date, r.check_out_date, r.reservation_status from {{ ref('stg_oracle_reservation_room') }} rr join {{ ref('stg_oracle_reservation') }} r using (reservation_id))
select
  rooms.property_id,
  rooms.room_id,
  date_day,
  count_if(rr.reservation_id is not null and rr.reservation_status not in ('CANCELLED', 'NO_SHOW')) > 0 as is_occupied
from rooms
cross join lateral (
  select dateadd(day, seq4(), current_date() - 30) as date_day from table(generator(rowcount => 396))
) dates
left join reservation_rooms rr on rooms.room_id = rr.room_id and date_day >= rr.check_in_date and date_day < rr.check_out_date
group by 1, 2, 3

