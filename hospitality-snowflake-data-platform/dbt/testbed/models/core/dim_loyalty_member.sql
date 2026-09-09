select loyalty_id, guest_id, tier, points_balance, joined_date, _generation_id, _ingested_at
from {{ ref('stg_loyalty_members') }}
