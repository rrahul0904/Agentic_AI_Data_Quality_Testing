select * from {{ source('hospitality_raw', 'daily_rates') }}
qualify row_number() over (partition by rate_id, _generation_id order by _ingested_at desc) = 1
