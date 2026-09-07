SELECT o.date_day, p.property_code, p.property_name, o.total_rooms, o.occupied_rooms, o.occupancy_rate
FROM HOSPITALITY_DW.MART.MART_PROPERTY_OCCUPANCY o
JOIN HOSPITALITY_DW.CORE.DIM_PROPERTY p USING (property_key)
WHERE o.date_day BETWEEN CURRENT_DATE() - 30 AND CURRENT_DATE() + 90
ORDER BY o.date_day, p.property_code;

