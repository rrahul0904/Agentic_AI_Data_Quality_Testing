select * from {{ source('hospitality_raw', 'refunds') }}
qualify row_number() over (partition by refund_id, _generation_id order by refund_ts desc, _ingested_at desc) = 1
