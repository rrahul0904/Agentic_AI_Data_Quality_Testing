select * from {{ source('hospitality_raw', 'cancellations') }}
qualify row_number() over (partition by cancellation_id, _generation_id order by cancelled_at desc, _ingested_at desc) = 1
