select * from {{ source('hospitality_raw', 'property_staff') }}
qualify row_number() over (partition by staff_id, _generation_id order by _ingested_at desc) = 1
