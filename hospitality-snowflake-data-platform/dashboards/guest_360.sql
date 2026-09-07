SELECT guest_key, country_code, guest_status, loyalty_tier, loyalty_points, lifetime_reservations,
       lifetime_room_nights, lifetime_value, cancellations, first_stay_date, latest_stay_date
FROM HOSPITALITY_DW.MART.MART_GUEST_360
WHERE guest_key = :guest_key;

