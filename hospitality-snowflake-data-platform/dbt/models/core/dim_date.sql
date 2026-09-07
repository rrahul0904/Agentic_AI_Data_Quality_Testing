{{ config(materialized='table') }}
with spine as (
  select dateadd(day, seq4(), '2020-01-01'::date) as date_day
  from table(generator(rowcount => 7305))
)
select
  to_number(to_char(date_day, 'YYYYMMDD')) as date_key,
  date_day,
  year(date_day) as calendar_year,
  quarter(date_day) as calendar_quarter,
  month(date_day) as calendar_month,
  weekiso(date_day) as iso_week,
  dayofweekiso(date_day) as iso_day_of_week,
  dayofweekiso(date_day) in (6, 7) as is_weekend
from spine

