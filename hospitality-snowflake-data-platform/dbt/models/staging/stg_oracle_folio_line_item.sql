with source as ({{ stage_raw_entity('oracle', 'FOLIO_LINE_ITEM') }})
select coalesce(raw_payload:FOLIO_LINE_ITEM_ID::varchar, source_primary_key) as folio_line_item_id,
       raw_payload:FOLIO_ID::varchar as folio_id, raw_payload:RESERVATION_ID::varchar as reservation_id,
       upper(raw_payload:LINE_ITEM_TYPE::varchar) as line_item_type, {{ safe_cast_number('raw_payload:AMOUNT') }} as line_item_amount,
       coalesce(raw_payload:CURRENCY_CODE::varchar, 'USD') as currency_code, {{ audit_columns() }} from source

