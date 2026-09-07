with source as ({{ stage_raw_entity('oracle', 'GUEST_PROFILE') }})
select
  coalesce(raw_payload:GUEST_PROFILE_ID::varchar, source_primary_key) as guest_profile_id,
  raw_payload:GUEST_ID::varchar as guest_id,
  raw_payload:LANGUAGE_CODE::varchar as preferred_language,
  raw_payload:COUNTRY_CODE::varchar as country_code,
  coalesce(try_to_timestamp_tz(raw_payload:SOURCE_UPDATED_AT::varchar), ingested_at) as updated_at,
  {{ audit_columns() }}
from source

