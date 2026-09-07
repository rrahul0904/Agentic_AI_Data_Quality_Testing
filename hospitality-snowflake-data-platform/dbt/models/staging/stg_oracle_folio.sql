with source as ({{ stage_raw_entity('oracle', 'FOLIO') }})
select
  coalesce(raw_payload:FOLIO_ID::varchar, source_primary_key) as folio_id,
  raw_payload:RESERVATION_ID::varchar as reservation_id,
  {{ safe_cast_number('raw_payload:AMOUNT') }} as folio_amount,
  coalesce(raw_payload:CURRENCY_CODE::varchar, 'USD') as currency_code,
  {{ audit_columns() }}
from source

