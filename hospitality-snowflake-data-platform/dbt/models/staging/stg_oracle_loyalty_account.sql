with source as ({{ stage_raw_entity('oracle', 'LOYALTY_ACCOUNT') }})
select
  coalesce(raw_payload:LOYALTY_ACCOUNT_ID::varchar, source_primary_key) as loyalty_account_id,
  raw_payload:GUEST_ID::varchar as guest_id,
  raw_payload:TIER_CODE::varchar as loyalty_tier,
  try_to_number(raw_payload:POINT_BALANCE) as point_balance,
  upper(raw_payload:STATUS::varchar) as loyalty_status,
  {{ audit_columns() }}
from source

