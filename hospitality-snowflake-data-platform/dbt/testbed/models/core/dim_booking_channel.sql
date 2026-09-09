select channel_id, initcap(replace(channel_id, '_', ' ')) as channel_name,
       iff(channel_id in ('EXPEDIA', 'BOOKING'), 'OTA', iff(channel_id = 'CORPORATE', 'B2B', 'DIRECT')) as channel_group,
       _generation_id, max(_ingested_at) as _ingested_at
from {{ ref('stg_channel_bookings') }}
group by channel_id, _generation_id
