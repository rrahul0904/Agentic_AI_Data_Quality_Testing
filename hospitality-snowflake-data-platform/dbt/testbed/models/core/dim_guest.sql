select guest_id, first_name, last_name, email, country, created_at, marketing_opt_in,
       _generation_id, _ingested_at
from {{ ref('stg_guests') }}
