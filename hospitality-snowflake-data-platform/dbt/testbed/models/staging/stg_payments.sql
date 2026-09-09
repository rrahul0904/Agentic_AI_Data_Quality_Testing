select * from {{ source('hospitality_raw', 'payments') }}
qualify row_number() over (partition by payment_id, _generation_id order by payment_ts desc, _ingested_at desc) = 1
