SELECT p.property_code, p.property_name, SUM(k.net_revenue) AS net_revenue,
       SUM(k.room_nights_booked) AS room_nights, SUM(k.net_revenue) / NULLIF(SUM(k.room_nights_booked), 0) AS adr
FROM HOSPITALITY_DW.MART.MART_EXECUTIVE_DAILY_KPIS k
JOIN HOSPITALITY_DW.CORE.DIM_PROPERTY p USING (property_key)
WHERE k.metric_date >= DATEADD(month, -12, CURRENT_DATE())
GROUP BY 1, 2 ORDER BY net_revenue DESC;

