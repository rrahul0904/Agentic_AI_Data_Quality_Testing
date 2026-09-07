{% macro generate_surrogate_key(fields) -%}
  sha2(concat_ws('||', {% for field in fields %}coalesce(cast({{ field }} as varchar), '__NULL__'){% if not loop.last %}, {% endif %}{% endfor %}), 256)
{%- endmacro %}

{% macro standardize_timestamp(expression) -%}
  try_to_timestamp_tz({{ expression }})
{%- endmacro %}

{% macro standardize_boolean(expression) -%}
  case
    when lower(cast({{ expression }} as varchar)) in ('true', 't', '1', 'yes', 'y') then true
    when lower(cast({{ expression }} as varchar)) in ('false', 'f', '0', 'no', 'n') then false
    else null
  end
{%- endmacro %}

{% macro record_hash(fields) -%}
  {{ generate_surrogate_key(fields) }}
{%- endmacro %}

{% macro safe_cast_number(expression, precision=18, scale=2) -%}
  try_to_decimal({{ expression }}, {{ precision }}, {{ scale }})
{%- endmacro %}

{% macro audit_columns() -%}
  ingestion_batch_id,
  ingested_at as loaded_at,
  source_system,
  source_file_name,
  record_hash
{%- endmacro %}

{% macro stage_raw_entity(source_system, source_entity) -%}
select
  raw_record_id,
  raw_payload,
  source_primary_key,
  ingestion_batch_id,
  ingested_at,
  source_system,
  source_file_name,
  record_hash,
  is_deleted
from {{ source('raw_' ~ source_system, 'raw_ingestion_events') }}
where lower(source_system) = lower('{{ source_system }}')
  and lower(source_table) = lower('{{ source_entity }}')
  and not coalesce(is_deleted, false)
qualify row_number() over (
  partition by coalesce(source_primary_key, record_hash)
  order by coalesce(source_updated_at, ingested_at) desc, ingested_at desc
) = 1
{%- endmacro %}

