{{ config(materialized='incremental', unique_key='event_id', incremental_strategy='merge') }}
with source as ({{ stage_raw_entity('files', 'clickstream_events.jsonl') }}),
typed as (
select
  raw_payload:event_id::varchar as event_id,
  raw_payload:anonymous_id::varchar as anonymous_id,
  raw_payload:session_id::varchar as session_id,
  raw_payload:event_name::varchar as event_name,
  raw_payload:property_id::varchar as property_id,
  raw_payload:channel::varchar as channel,
  try_to_timestamp_tz(raw_payload:event_timestamp::varchar) as event_timestamp,
  {{ audit_columns() }}
from source
)
select * from typed
where event_id is not null and event_timestamp is not null
{% if is_incremental() %}
  and loaded_at >= dateadd(hour, -{{ var('raw_lookback_hours') }}, (select max(loaded_at) from {{ this }}))
{% endif %}
