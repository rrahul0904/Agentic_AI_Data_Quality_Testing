SELECT c.channel_name, COUNT(*) AS events, COUNT_IF(f.event_name = 'checkout') AS checkout_events,
       checkout_events / NULLIF(events, 0) AS checkout_rate
FROM HOSPITALITY_DW.CORE.FACT_CLICKSTREAM_EVENT f
JOIN HOSPITALITY_DW.CORE.DIM_CHANNEL c USING (channel_key)
WHERE f.event_timestamp >= DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY checkout_events DESC;

