with source as ({{ stage_raw_entity('postgres', 'search_request') }})
select
  coalesce(raw_payload:search_request_id::varchar, source_primary_key) as search_request_id,
  raw_payload:app_user_id::varchar as app_user_id,
  raw_payload:session_id::varchar as session_id,
  raw_payload:property_id::varchar as property_id,
  try_to_timestamp_tz(raw_payload:source_created_at::varchar) as searched_at,
  {{ audit_columns() }}
from source

