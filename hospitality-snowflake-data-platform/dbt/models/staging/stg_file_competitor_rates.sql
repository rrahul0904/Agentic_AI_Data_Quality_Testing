with source as ({{ stage_raw_entity('files', 'competitor_rate_shops.parquet') }})
select raw_payload:rate_shop_id::varchar as rate_shop_id, raw_payload:property_id::varchar as property_id,
       raw_payload:competitor_property_id::varchar as competitor_property_id, raw_payload:room_type::varchar as room_type_code,
       try_to_date(raw_payload:stay_date::varchar) as stay_date, raw_payload:currency::varchar as currency_code,
       {{ safe_cast_number('raw_payload:observed_rate') }} as competitor_rate,
       {{ standardize_boolean('raw_payload:available') }} as is_available, {{ audit_columns() }} from source

