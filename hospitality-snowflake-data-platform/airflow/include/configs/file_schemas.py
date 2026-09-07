"""Reviewed schemas for local CSV feeds and Snowflake object construction."""

FILE_SCHEMAS: dict[str, tuple[str, ...]] = {
    "partner_bookings.csv": (
        "load_date", "source_file_name", "source_system", "event_timestamp", "partner_booking_id",
        "partner_id", "property_id", "status", "check_in_date", "check_out_date", "currency",
        "gross_amount", "commission_amount",
    ),
    "third_party_rates.csv": (
        "load_date", "source_file_name", "source_system", "event_timestamp", "rate_shop_id", "property_id",
        "competitor_property_id", "room_type", "stay_date", "currency", "observed_rate", "available",
    ),
    "payment_gateway_settlements.csv": (
        "load_date", "source_file_name", "source_system", "event_timestamp", "settlement_id", "transaction_id",
        "gateway", "settlement_date", "currency", "gross_amount", "fee_amount", "net_amount", "status",
    ),
}

GENERIC_CSV_SCHEMA = (
    "load_date", "source_file_name", "source_system", "event_timestamp", "record_id", "property_id",
    "guest_id", "event_type", "status", "amount", "notes",
)

for _filename in (
    "call_center_interactions.csv",
    "guest_review_exports.csv",
    "inventory_adjustments.csv",
    "email_marketing_events.csv",
    "loyalty_partner_transactions.csv",
    "weather_by_property.csv",
    "local_events_calendar.csv",
    "restaurant_pos_transactions.csv",
    "spa_pos_transactions.csv",
    "housekeeping_inspection_scores.csv",
):
    FILE_SCHEMAS[_filename] = GENERIC_CSV_SCHEMA


def csv_payload_expression(filename: str) -> str:
    columns = FILE_SCHEMAS.get(filename)
    if columns is None:
        raise ValueError(f"No reviewed CSV schema is registered for {filename}")
    pairs = ",".join(f"'{name}',${position}" for position, name in enumerate(columns, start=1))
    return f"OBJECT_CONSTRUCT_KEEP_NULL({pairs})"
