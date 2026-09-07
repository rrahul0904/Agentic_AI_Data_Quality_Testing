with source as ({{ stage_raw_entity('postgres', 'promo_redemption') }})
select coalesce(raw_payload:promo_redemption_id::varchar, source_primary_key) as promo_redemption_id,
       raw_payload:promo_campaign_id::varchar as promo_campaign_id, raw_payload:app_user_id::varchar as app_user_id,
       raw_payload:reservation_id::varchar as reservation_id, {{ safe_cast_number('raw_payload:discount_amount') }} as discount_amount,
       try_to_timestamp_tz(raw_payload:redeemed_at::varchar) as redeemed_at, {{ audit_columns() }} from source

