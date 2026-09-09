with source_counts as (
  select _generation_id, count(*) as source_rows from {{ ref('stg_reservations') }} group by _generation_id
), target_counts as (
  select _generation_id, count(*) as target_rows from {{ ref('fact_reservation') }} group by _generation_id
)
select * from source_counts full outer join target_counts using (_generation_id)
where coalesce(source_rows, 0) != coalesce(target_rows, 0)
