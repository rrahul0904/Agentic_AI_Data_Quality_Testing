{% snapshot snap_guest_profile %}
{{ config(target_schema='CORE', unique_key='guest_profile_id', strategy='timestamp', updated_at='updated_at', invalidate_hard_deletes=True) }}
select * from {{ ref('stg_oracle_guest_profile') }}
{% endsnapshot %}

