"""The reviewed ingestion-job catalog used by the dynamic DAG factory."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestionJob:
    dag_id: str
    source: str
    entities: tuple[str, ...]
    load_strategy: str = "timestamp_incremental"


def job(dag_id: str, source: str, *entities: str, strategy: str = "timestamp_incremental") -> IngestionJob:
    return IngestionJob(dag_id, source, entities, strategy)


INGESTION_JOBS = (
    job("01_oracle_property_master_ingest", "oracle", "HOTEL_PROPERTY", "HOTEL_BRAND", "HOTEL_REGION"),
    job("02_oracle_room_inventory_ingest", "oracle", "ROOM", "ROOM_TYPE", "ROOM_INVENTORY"),
    job("03_oracle_room_rate_plan_ingest", "oracle", "ROOM_RATE_PLAN", "ROOM_RATE_RULE"),
    job("04_oracle_rate_calendar_ingest", "oracle", "ROOM_RATE_CALENDAR", strategy="high_watermark"),
    job("05_oracle_guest_profile_ingest", "oracle", "GUEST", "GUEST_PROFILE", "GUEST_ADDRESS"),
    job("06_oracle_guest_preferences_ingest", "oracle", "GUEST_PREFERENCE", "GUEST_CONSENT"),
    job("07_oracle_reservation_header_ingest", "oracle", "RESERVATION"),
    job("08_oracle_reservation_room_ingest", "oracle", "RESERVATION_ROOM"),
    job("09_oracle_reservation_status_history_ingest", "oracle", "RESERVATION_STATUS_HISTORY", strategy="append_only"),
    job("10_oracle_checkin_checkout_ingest", "oracle", "CHECKIN", "CHECKOUT"),
    job("11_oracle_folio_ingest", "oracle", "FOLIO"),
    job("12_oracle_folio_line_item_ingest", "oracle", "FOLIO_LINE_ITEM", strategy="high_watermark"),
    job("13_oracle_loyalty_account_ingest", "oracle", "LOYALTY_ACCOUNT"),
    job("14_oracle_loyalty_transaction_ingest", "oracle", "LOYALTY_TRANSACTION", strategy="append_only"),
    job("15_oracle_housekeeping_task_ingest", "oracle", "HOUSEKEEPING_TASK", "HOUSEKEEPING_ASSIGNMENT"),
    job("16_oracle_maintenance_ticket_ingest", "oracle", "MAINTENANCE_TICKET", "MAINTENANCE_WORK_ORDER"),
    job("17_oracle_restaurant_reservation_ingest", "oracle", "RESTAURANT_RESERVATION"),
    job("18_oracle_spa_booking_ingest", "oracle", "SPA_BOOKING"),
    job("19_oracle_event_booking_ingest", "oracle", "EVENT_BOOKING"),
    job("20_oracle_channel_partner_ingest", "oracle", "CHANNEL_PARTNER", "PARTNER_COMMISSION"),
    job("21_postgres_user_identity_ingest", "postgres", "app_user", "user_identity"),
    job("22_postgres_user_session_ingest", "postgres", "user_session", strategy="append_only"),
    job("23_postgres_search_request_ingest", "postgres", "search_request", strategy="append_only"),
    job("24_postgres_search_result_ingest", "postgres", "search_result", strategy="append_only"),
    job("25_postgres_booking_cart_ingest", "postgres", "booking_cart", "booking_cart_item"),
    job("26_postgres_booking_attempt_ingest", "postgres", "booking_attempt", strategy="append_only"),
    job("27_postgres_booking_confirmation_ingest", "postgres", "booking_confirmation"),
    job("28_postgres_payment_transaction_ingest", "postgres", "payment_transaction", strategy="high_watermark"),
    job("29_postgres_refund_transaction_ingest", "postgres", "refund_transaction", strategy="high_watermark"),
    job("30_postgres_promo_campaign_ingest", "postgres", "promo_campaign"),
    job("31_postgres_promo_redemption_ingest", "postgres", "promo_redemption", strategy="append_only"),
    job("32_postgres_guest_review_ingest", "postgres", "guest_review"),
    job("33_postgres_support_ticket_ingest", "postgres", "support_ticket", "support_message"),
    job("34_postgres_notification_event_ingest", "postgres", "notification", "email_event", "sms_event", "push_event", strategy="append_only"),
    job("35_postgres_marketing_touchpoint_ingest", "postgres", "marketing_touchpoint", "attribution_event", strategy="append_only"),
    job("36_postgres_fraud_signal_ingest", "postgres", "fraud_signal", "risk_score", strategy="append_only"),
    job("37_file_clickstream_ingest", "files", "clickstream_events.jsonl", strategy="append_only"),
    job("38_file_partner_bookings_ingest", "files", "partner_bookings.csv", strategy="file_manifest"),
    job("39_file_payment_settlement_ingest", "files", "payment_gateway_settlements.csv", strategy="file_manifest"),
    job(
        "40_file_operational_feeds_ingest", "files", "inventory_adjustments.csv",
        "housekeeping_inspection_scores.csv", "maintenance_sensor_events.jsonl", strategy="file_manifest",
    ),
)

assert len(INGESTION_JOBS) == 40

