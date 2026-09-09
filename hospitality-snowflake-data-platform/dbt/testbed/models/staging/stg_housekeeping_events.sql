select * from {{ source('hospitality_raw', 'housekeeping_events') }}
qualify row_number() over (partition by event_id, _generation_id order by event_ts desc, _ingested_at desc) = 1
