with source as ({{ stage_raw_entity('oracle', 'GUEST') }})
select
  coalesce(raw_payload:GUEST_ID::varchar, raw_payload:guest_id::varchar, source_primary_key) as guest_id,
  coalesce(raw_payload:EXTERNAL_REFERENCE::varchar, raw_payload:external_reference::varchar) as external_guest_reference,
  coalesce(raw_payload:COUNTRY_CODE::varchar, raw_payload:country_code::varchar) as country_code,
  coalesce(raw_payload:STATUS::varchar, raw_payload:status::varchar) as guest_status,
  {{ audit_columns() }}
from source

