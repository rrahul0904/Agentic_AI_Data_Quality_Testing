SELECT property_id, DATE_TRUNC('week', opened_at) AS opened_week, COUNT(*) AS tickets,
       AVG(DATEDIFF(hour, opened_at, resolved_at)) AS average_resolution_hours,
       COUNT_IF(resolved_at IS NULL) AS unresolved_tickets
FROM HOSPITALITY_DW.STAGING.STG_ORACLE_MAINTENANCE_TICKET
GROUP BY 1, 2 ORDER BY 2 DESC, unresolved_tickets DESC;

