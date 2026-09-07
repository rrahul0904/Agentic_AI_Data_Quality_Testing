with channels as (
  select distinct booking_channel as channel_code from {{ ref('stg_oracle_reservation') }}
  union
  select distinct channel from {{ ref('stg_file_clickstream_events') }}
)
select {{ generate_surrogate_key(['channel_code']) }} as channel_key, channel_code,
       initcap(replace(channel_code, '_', ' ')) as channel_name
from channels where channel_code is not null

