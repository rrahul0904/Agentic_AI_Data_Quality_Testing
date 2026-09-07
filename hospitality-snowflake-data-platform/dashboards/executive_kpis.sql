SELECT metric_date, SUM(net_revenue) AS net_revenue, SUM(total_reservations) AS reservations,
       SUM(room_nights_booked) AS room_nights_booked,
       SUM(net_revenue) / NULLIF(SUM(room_nights_booked), 0) AS adr,
       SUM(net_revenue) / NULLIF(SUM(room_nights_booked / NULLIF(occupancy_rate, 0)), 0) AS revpar
FROM HOSPITALITY_DW.MART.MART_EXECUTIVE_DAILY_KPIS
WHERE metric_date >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1 ORDER BY 1;

