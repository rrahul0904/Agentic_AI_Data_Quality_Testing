with source as ({{ stage_raw_entity('postgres', 'search_result') }})
select coalesce(raw_payload:search_result_id::varchar, source_primary_key) as search_result_id,
       raw_payload:search_request_id::varchar as search_request_id, raw_payload:property_id::varchar as property_id,
       try_to_number(raw_payload:rank_position) as rank_position, {{ safe_cast_number('raw_payload:displayed_rate') }} as displayed_rate,
       {{ audit_columns() }} from source

