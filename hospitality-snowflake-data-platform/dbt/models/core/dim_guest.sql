select
  guest_key,
  guest_id,
  app_user_id,
  external_guest_reference,
  country_code,
  guest_status,
  loaded_at as updated_at
from {{ ref('int_guest_identity_resolution') }}

