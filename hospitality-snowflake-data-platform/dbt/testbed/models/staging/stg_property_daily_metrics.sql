select * from {{ source('hospitality_raw', 'property_daily_metrics') }}
qualify row_number() over (partition by metric_id, _generation_id order by _ingested_at desc) = 1
