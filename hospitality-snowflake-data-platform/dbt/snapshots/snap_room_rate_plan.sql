{% snapshot snap_room_rate_plan %}
{{ config(target_schema='CORE', unique_key='rate_plan_id', strategy='timestamp', updated_at='updated_at', invalidate_hard_deletes=True) }}
select * from {{ ref('stg_oracle_room_rate_plan') }}
{% endsnapshot %}

