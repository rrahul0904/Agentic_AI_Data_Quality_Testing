select
  housekeeping_task_id,
  room_id,
  task_status,
  assigned_at,
  completed_at,
  datediff(minute, assigned_at, completed_at) as turnaround_minutes,
  datediff(minute, assigned_at, completed_at) <= 45 as met_cleaning_sla,
  loaded_at
from {{ ref('stg_oracle_housekeeping_task') }}

