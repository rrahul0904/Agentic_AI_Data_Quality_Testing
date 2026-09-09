with spine as (
  select dateadd(day, seq4(), '2020-01-01'::date) as date_day
  from table(generator(rowcount => 7305))
)
select date_day, year(date_day) as year_number, month(date_day) as month_number,
       day(date_day) as day_of_month, dayofweekiso(date_day) as day_of_week,
       iff(dayofweekiso(date_day) in (6, 7), true, false) as is_weekend
from spine
