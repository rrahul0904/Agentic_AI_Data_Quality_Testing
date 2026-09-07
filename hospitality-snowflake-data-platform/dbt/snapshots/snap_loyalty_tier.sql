{% snapshot snap_loyalty_tier %}
{{ config(target_schema='CORE', unique_key='loyalty_account_id', strategy='check', check_cols=['loyalty_tier', 'loyalty_status'], invalidate_hard_deletes=True) }}
select * from {{ ref('stg_oracle_loyalty_account') }}
{% endsnapshot %}

