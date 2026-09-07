select
  to_date(assigned_at) as operation_date,
  count(*) as assigned_tasks,
  count_if(task_status = 'COMPLETED') as completed_tasks,
  avg(turnaround_minutes) as average_turnaround_minutes,
  count_if(met_cleaning_sla) / nullif(count_if(completed_at is not null), 0) as cleaning_sla_rate
from {{ ref('int_housekeeping_room_turnover') }}
group by 1

