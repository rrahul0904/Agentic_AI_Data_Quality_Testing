select * from {{ ref('mart_daily_occupancy') }} where occupied_rooms > available_rooms or occupancy_pct not between 0 and 100
