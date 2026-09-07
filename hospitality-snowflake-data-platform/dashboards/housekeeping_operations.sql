SELECT operation_date, assigned_tasks, completed_tasks, average_turnaround_minutes, cleaning_sla_rate
FROM HOSPITALITY_DW.MART.MART_OPERATIONS_HOUSEKEEPING
WHERE operation_date >= DATEADD(day, -30, CURRENT_DATE())
ORDER BY operation_date;

