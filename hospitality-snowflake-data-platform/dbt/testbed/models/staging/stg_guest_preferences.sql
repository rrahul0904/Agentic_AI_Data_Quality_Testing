select * from {{ source('hospitality_raw', 'guest_preferences') }}
qualify row_number() over (partition by preference_id, _generation_id order by updated_at desc, _ingested_at desc) = 1
