select * from {{ source('hospitality_raw', 'folio_charges') }}
qualify row_number() over (partition by folio_id, _generation_id order by charge_ts desc, _ingested_at desc) = 1
