{{ config(materialized='incremental', unique_key='event_key', incremental_strategy='merge') }}
select
  {{ generate_surrogate_key(['event_id']) }} as event_key,
  event_id,
  anonymous_id,
  session_id,
  event_name,
  {{ generate_surrogate_key(['property_id']) }} as property_key,
  {{ generate_surrogate_key(['channel']) }} as channel_key,
  event_timestamp,
  loaded_at
from {{ ref('stg_file_clickstream_events') }}
{% if is_incremental() %}where loaded_at >= dateadd(hour, -72, (select max(loaded_at) from {{ this }})){% endif %}

