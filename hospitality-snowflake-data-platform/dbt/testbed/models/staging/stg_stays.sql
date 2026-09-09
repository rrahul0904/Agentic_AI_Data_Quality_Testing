select * from {{ source('hospitality_raw', 'stays') }}
qualify row_number() over (partition by stay_id, _generation_id order by actual_checkout_at desc, _ingested_at desc) = 1
