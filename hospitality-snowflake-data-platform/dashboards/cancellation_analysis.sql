SELECT p.property_name, r.channel_key, COUNT(*) AS reservations, COUNT_IF(r.is_cancelled) AS cancellations,
       cancellations / NULLIF(reservations, 0) AS cancellation_rate,
       SUM(IFF(r.is_cancelled, r.gross_booking_value, 0)) AS cancelled_value
FROM HOSPITALITY_DW.CORE.FACT_RESERVATION r
JOIN HOSPITALITY_DW.CORE.DIM_PROPERTY p USING (property_key)
GROUP BY 1, 2 ORDER BY cancellation_rate DESC;

