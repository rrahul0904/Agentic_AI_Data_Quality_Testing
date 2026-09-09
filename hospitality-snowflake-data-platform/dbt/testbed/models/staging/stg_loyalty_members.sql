select * from {{ source('hospitality_raw', 'loyalty_members') }}
qualify row_number() over (partition by loyalty_id, _generation_id order by _ingested_at desc) = 1
