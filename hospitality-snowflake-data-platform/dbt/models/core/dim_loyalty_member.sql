select
  {{ generate_surrogate_key(['loyalty_account_id']) }} as loyalty_member_key,
  loyalty_account_id,
  {{ generate_surrogate_key(['guest_id']) }} as guest_key,
  guest_id,
  loyalty_tier,
  point_balance,
  loyalty_status,
  loaded_at as updated_at
from {{ ref('stg_oracle_loyalty_account') }}

