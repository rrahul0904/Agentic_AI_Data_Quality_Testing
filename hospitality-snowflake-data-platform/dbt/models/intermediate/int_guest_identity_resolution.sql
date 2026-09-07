with oracle_guest as (select * from {{ ref('stg_oracle_guest') }}),
app_user as (select * from {{ ref('stg_postgres_app_user') }})
select
  {{ generate_surrogate_key(['coalesce(g.guest_id, u.app_user_id)']) }} as guest_key,
  g.guest_id,
  u.app_user_id,
  coalesce(g.external_guest_reference, u.external_user_reference) as external_guest_reference,
  g.country_code,
  coalesce(g.guest_status, u.user_status, 'UNKNOWN') as guest_status,
  greatest_ignore_nulls(g.loaded_at, u.loaded_at) as loaded_at
from oracle_guest g
full outer join app_user u on g.external_guest_reference = u.external_user_reference

