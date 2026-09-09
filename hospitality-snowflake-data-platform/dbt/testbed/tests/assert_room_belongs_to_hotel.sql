select r.* from {{ ref('dim_room') }} r left join {{ ref('dim_hotel') }} h using (hotel_id, _generation_id) where h.hotel_id is null
