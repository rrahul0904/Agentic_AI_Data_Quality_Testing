with source as ({{ stage_raw_entity('oracle', 'HOTEL_PROPERTY') }})
select
  coalesce(raw_payload:HOTEL_PROPERTY_ID::varchar, raw_payload:hotel_property_id::varchar, source_primary_key) as property_id,
  coalesce(raw_payload:PROPERTY_CODE::varchar, raw_payload:property_code::varchar) as property_code,
  coalesce(raw_payload:PROPERTY_NAME::varchar, raw_payload:property_name::varchar) as property_name,
  coalesce(raw_payload:STATUS::varchar, raw_payload:status::varchar) as property_status,
  {{ audit_columns() }}
from source

