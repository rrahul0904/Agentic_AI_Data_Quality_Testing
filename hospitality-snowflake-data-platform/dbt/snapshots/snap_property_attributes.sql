{% snapshot snap_property_attributes %}
{{ config(target_schema='CORE', unique_key='property_id', strategy='check', check_cols=['property_code', 'property_name', 'property_status'], invalidate_hard_deletes=True) }}
select * from {{ ref('stg_oracle_hotel_property') }}
{% endsnapshot %}

