SELECT metric_date, sessions, searches, digital_events, checkout_sessions, checkout_conversion_rate
FROM HOSPITALITY_DW.MART.MART_BOOKING_CONVERSION
WHERE metric_date >= DATEADD(day, -90, CURRENT_DATE())
ORDER BY metric_date;

