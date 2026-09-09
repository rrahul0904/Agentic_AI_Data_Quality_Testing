select to_date(event_ts) as event_date, channel_id, _generation_id,
       count_if(event_type = 'SEARCH') as searches,
       count_if(event_type = 'CHECKOUT_STARTED') as checkouts_started,
       count_if(event_type = 'BOOKED') as bookings,
       round(100.0 * count_if(event_type = 'BOOKED') / nullif(count_if(event_type = 'SEARCH'), 0), 2) as conversion_pct
from {{ ref('stg_web_booking_events') }}
group by to_date(event_ts), channel_id, _generation_id
