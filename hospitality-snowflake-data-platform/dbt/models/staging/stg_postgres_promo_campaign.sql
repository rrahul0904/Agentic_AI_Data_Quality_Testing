with source as ({{ stage_raw_entity('postgres', 'promo_campaign') }})
select coalesce(raw_payload:promo_campaign_id::varchar, source_primary_key) as promo_campaign_id,
       raw_payload:promo_code::varchar as promo_code, raw_payload:campaign_name::varchar as campaign_name,
       upper(raw_payload:status::varchar) as campaign_status, try_to_timestamp_tz(raw_payload:starts_at::varchar) as starts_at,
       try_to_timestamp_tz(raw_payload:ends_at::varchar) as ends_at, {{ safe_cast_number('raw_payload:budget_amount') }} as budget_amount,
       {{ audit_columns() }} from source

