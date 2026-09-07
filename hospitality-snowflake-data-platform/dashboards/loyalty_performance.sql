SELECT loyalty_tier, COUNT(*) AS members, SUM(loyalty_points) AS outstanding_points,
       AVG(lifetime_value) AS average_lifetime_value, AVG(lifetime_reservations) AS average_reservations
FROM HOSPITALITY_DW.MART.MART_GUEST_360
GROUP BY 1 ORDER BY average_lifetime_value DESC;

