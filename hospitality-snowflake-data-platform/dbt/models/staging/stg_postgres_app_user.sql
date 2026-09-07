with source as ({{ stage_raw_entity('postgres', 'app_user') }})
select
  coalesce(raw_payload:app_user_id::varchar, source_primary_key) as app_user_id,
  raw_payload:external_reference::varchar as external_user_reference,
  upper(raw_payload:status::varchar) as user_status,
  {{ audit_columns() }}
from source

