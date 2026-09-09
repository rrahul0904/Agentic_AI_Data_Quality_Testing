with duplicate_keys as (
  select 'dim_hotel' as model_name, hotel_id as business_key, _generation_id
  from {{ ref('dim_hotel') }} group by hotel_id, _generation_id having count(*) > 1
  union all
  select 'dim_room', room_id, _generation_id
  from {{ ref('dim_room') }} group by room_id, _generation_id having count(*) > 1
  union all
  select 'dim_guest', guest_id, _generation_id
  from {{ ref('dim_guest') }} group by guest_id, _generation_id having count(*) > 1
  union all
  select 'fact_reservation', reservation_id, _generation_id
  from {{ ref('fact_reservation') }} group by reservation_id, _generation_id having count(*) > 1
  union all
  select 'fact_payment', payment_id, _generation_id
  from {{ ref('fact_payment') }} group by payment_id, _generation_id having count(*) > 1
  union all
  select 'fact_stay', stay_id, _generation_id
  from {{ ref('fact_stay') }} group by stay_id, _generation_id having count(*) > 1
)
select * from duplicate_keys
