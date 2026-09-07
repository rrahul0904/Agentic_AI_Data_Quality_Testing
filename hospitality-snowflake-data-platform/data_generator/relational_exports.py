"""Generate simulated Oracle/PostgreSQL CDC export files for local Airflow runs."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_generator.faker_config import DEFAULT_SEED, get_scale
from data_generator.source_catalog import ORACLE_TABLES, POSTGRES_TABLES


def target_rows(table: str, scale_name: str) -> int:
    scale = get_scale(scale_name)
    name = table.lower()
    if name in {"reservation", "booking_confirmation"}:
        return scale.reservations
    if name in {"guest", "app_user"}:
        return scale.guests
    if any(token in name for token in ("property", "hotel", "brand", "region")):
        return max(scale.properties, 10)
    if any(token in name for token in ("guest", "user", "identity", "loyalty_account")):
        return max(scale.guests // 10, 100)
    if any(token in name for token in ("reservation", "booking", "payment", "folio")):
        return max(scale.reservations // 30, 100)
    if any(token in name for token in ("event", "session", "search", "log", "history", "transaction")):
        # Event-like entities share the scale's overall event budget rather than
        # each independently generating that many rows.
        return max(scale.events // 50, 100)
    return max(scale.properties * 10, 100)


def make_row(
    source: str, table: str, i: int, rng: random.Random, now: datetime, property_count: int, guest_count: int
) -> dict[str, Any]:
    upper = source == "oracle"
    id_name = f"{table}_ID" if upper else f"{table}_id"
    created = now - timedelta(days=rng.randrange(1, 730))
    updated = created + timedelta(days=rng.randrange(0, max(1, (now - created).days)))
    row: dict[str, Any] = {
        id_name: i + 1,
        "SOURCE_CREATED_AT" if upper else "source_created_at": created.isoformat(),
        "SOURCE_UPDATED_AT" if upper else "source_updated_at": updated.isoformat(),
        "IS_DELETED" if upper else "is_deleted": rng.random() < 0.002,
    }
    key = (lambda value: value.upper()) if upper else (lambda value: value.lower())
    row[key("STATUS")] = rng.choice(["CONFIRMED", "COMPLETED", "ACTIVE", "CANCELLED", "PENDING"])
    row[key("PROPERTY_ID")] = rng.randrange(1, property_count + 1)
    if any(token in table.lower() for token in ("guest", "reservation", "booking", "loyalty")):
        row[key("GUEST_ID")] = rng.randrange(1, guest_count + 1)
    if any(token in table.lower() for token in ("reservation", "booking")):
        check_in = now.date() + timedelta(days=rng.randrange(-60, 180))
        row[key("CHECK_IN_DATE")] = check_in.isoformat()
        row[key("CHECK_OUT_DATE")] = (check_in + timedelta(days=rng.randrange(1, 9))).isoformat()
        row[key("TOTAL_AMOUNT")] = round(rng.uniform(90, 8_000), 2)
        row[key("CHANNEL_CODE")] = rng.choice(["DIRECT", "MOBILE", "OTA", "GDS", "CALL_CENTER"])
    if any(token in table.lower() for token in ("payment", "refund", "folio", "rate", "transaction")):
        row[key("AMOUNT")] = round(rng.uniform(1, 8_000), 2)
        row[key("CURRENCY_CODE")] = "USD"
    name = table.lower()
    property_id = row[key("PROPERTY_ID")]
    guest_id = rng.randrange(1, guest_count + 1)
    reservation_id = rng.randrange(1, max(i + 2, 101))
    room_id = rng.randrange(1, max(property_count * 100, 101))
    if name == "hotel_property":
        row.update({key("PROPERTY_CODE"): f"P{property_id:05d}", key("PROPERTY_NAME"): f"Synthetic Hotel {property_id}"})
    elif name == "room":
        row.update({key("ROOM_TYPE_ID"): rng.randrange(1, 6), key("ROOM_NUMBER"): f"{rng.randrange(1, 20)}{rng.randrange(1, 30):02d}"})
    elif name == "room_type":
        row.update({key("ROOM_TYPE_CODE"): rng.choice(["KING", "QUEEN", "DOUBLE", "SUITE"]), key("MAX_OCCUPANCY"): rng.randrange(1, 6)})
    elif name == "room_inventory":
        row.update({key("ROOM_TYPE_ID"): rng.randrange(1, 6), key("INVENTORY_DATE"): (now.date() + timedelta(days=i % 365)).isoformat(), key("AVAILABLE_ROOMS"): rng.randrange(0, 80)})
    elif name == "guest":
        row.update({key("EXTERNAL_REFERENCE"): f"GUEST-{i + 1:09d}", key("COUNTRY_CODE"): rng.choice(["US", "CA", "GB", "IN", "DE"])})
    elif name == "guest_profile":
        row.update({key("GUEST_ID"): guest_id, key("LANGUAGE_CODE"): rng.choice(["en", "es", "fr", "de"]), key("COUNTRY_CODE"): rng.choice(["US", "CA", "GB", "IN"])})
    elif name == "reservation_room":
        row.update({key("RESERVATION_ID"): reservation_id, key("ROOM_ID"): room_id, key("ROOM_TYPE_ID"): rng.randrange(1, 6), key("ROOM_RATE"): round(rng.uniform(80, 900), 2)})
    elif name == "reservation_status_history":
        row.update({key("RESERVATION_ID"): reservation_id, key("CHANGED_AT"): updated.isoformat()})
    elif name in {"checkin", "checkout"}:
        event_column = "CHECKED_IN_AT" if name == "checkin" else "CHECKED_OUT_AT"
        row.update({key("RESERVATION_ID"): reservation_id, key("GUEST_ID"): guest_id, key("ROOM_ID"): room_id, key(event_column): updated.isoformat()})
    elif name == "folio":
        row[key("RESERVATION_ID")] = reservation_id
    elif name == "folio_line_item":
        row.update({key("FOLIO_ID"): rng.randrange(1, max(i + 2, 101)), key("RESERVATION_ID"): reservation_id, key("LINE_ITEM_TYPE"): rng.choice(["ROOM", "TAX", "FOOD", "SPA"])})
    elif name == "room_rate_plan":
        row.update({key("RATE_PLAN_CODE"): f"RATE-{i % 12:02d}", key("RATE_PLAN_NAME"): rng.choice(["Flexible", "Advance Purchase", "Member Rate"])})
    elif name == "room_rate_calendar":
        row.update({key("ROOM_TYPE_ID"): rng.randrange(1, 6), key("STAY_DATE"): (now.date() + timedelta(days=i % 365)).isoformat()})
    elif name == "loyalty_account":
        row.update({key("GUEST_ID"): guest_id, key("TIER_CODE"): rng.choice(["MEMBER", "SILVER", "GOLD", "PLATINUM"]), key("POINT_BALANCE"): rng.randrange(0, 200_000)})
    elif name == "loyalty_transaction":
        row.update({key("LOYALTY_ACCOUNT_ID"): rng.randrange(1, max(i + 2, 101)), key("GUEST_ID"): guest_id, key("TRANSACTION_TYPE"): rng.choice(["EARN", "REDEEM", "EXPIRE"]), key("POINTS"): rng.randrange(100, 20_000), key("TRANSACTION_AT"): updated.isoformat()})
    elif name == "housekeeping_task":
        assigned = updated - timedelta(minutes=rng.randrange(15, 180))
        row.update({key("ROOM_ID"): room_id, key("EMPLOYEE_ID"): rng.randrange(1, 500), key("ASSIGNED_AT"): assigned.isoformat(), key("COMPLETED_AT"): updated.isoformat()})
    elif name == "maintenance_ticket":
        opened = updated - timedelta(hours=rng.randrange(1, 240))
        row.update({key("ROOM_ID"): room_id, key("OPENED_AT"): opened.isoformat(), key("RESOLVED_AT"): updated.isoformat(), key("PRIORITY"): rng.choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"])})
    elif name in {"restaurant_reservation", "spa_booking", "event_booking"}:
        row.update({key("GUEST_ID"): guest_id, key("RESERVATION_ID"): reservation_id, key("BOOKING_AT"): updated.isoformat(), key("SERVICE_DATE"): (now.date() + timedelta(days=i % 90)).isoformat(), key("PARTY_SIZE"): rng.randrange(1, 200 if name == "event_booking" else 10)})

    if source == "postgres":
        if name == "app_user":
            row.update({"external_reference": f"GUEST-{i + 1:09d}"})
        elif name == "user_session":
            row.update({"app_user_id": guest_id, "session_id": f"session-{i:010d}", "started_at": created.isoformat(), "ended_at": updated.isoformat()})
        elif name == "search_request":
            row.update({"app_user_id": guest_id, "session_id": f"session-{i:010d}", "searched_at": created.isoformat()})
        elif name == "search_result":
            row.update({"search_request_id": i + 1, "rank_position": i % 25 + 1, "displayed_rate": round(rng.uniform(80, 900), 2)})
        elif name == "booking_cart":
            row.update({"app_user_id": guest_id, "session_id": f"session-{i:010d}", "cart_amount": round(rng.uniform(80, 8_000), 2), "created_at": created.isoformat()})
        elif name == "booking_attempt":
            row.update({"booking_cart_id": i + 1, "session_id": f"session-{i:010d}", "attempted_at": created.isoformat(), "amount": round(rng.uniform(80, 8_000), 2)})
        elif name == "booking_confirmation":
            row.update({"reservation_id": reservation_id, "booking_attempt_id": i + 1, "confirmed_at": updated.isoformat()})
        elif name == "payment_transaction":
            row.update({"reservation_id": reservation_id, "payment_method_id": rng.randrange(1, 20), "transaction_at": updated.isoformat()})
        elif name == "refund_transaction":
            row.update({"payment_transaction_id": i + 1, "reservation_id": reservation_id, "refund_at": updated.isoformat(), "reason_code": rng.choice(["CANCELLATION", "SERVICE_RECOVERY", "DUPLICATE"])})
        elif name == "promo_campaign":
            row.update({"promo_code": f"PROMO{i % 20:02d}", "campaign_name": f"Synthetic Campaign {i % 20}", "starts_at": created.isoformat(), "ends_at": (updated + timedelta(days=30)).isoformat(), "budget_amount": round(rng.uniform(1_000, 100_000), 2)})
        elif name == "promo_redemption":
            row.update({"promo_campaign_id": rng.randrange(1, 21), "app_user_id": guest_id, "reservation_id": reservation_id, "discount_amount": round(rng.uniform(5, 300), 2), "redeemed_at": updated.isoformat()})
        elif name == "guest_review":
            row.update({"reservation_id": reservation_id, "guest_id": guest_id, "rating": rng.randrange(1, 6), "review_text": rng.choice(["excellent stay", "friendly staff", "room needed attention", "great location"]), "reviewed_at": updated.isoformat()})
        elif name == "support_ticket":
            row.update({"app_user_id": guest_id, "reservation_id": reservation_id, "category": rng.choice(["BOOKING", "PAYMENT", "STAY"]), "opened_at": created.isoformat(), "resolved_at": updated.isoformat()})
        elif name == "marketing_touchpoint":
            row.update({"app_user_id": guest_id, "session_id": f"session-{i:010d}", "marketing_campaign_id": rng.randrange(1, 21), "channel": rng.choice(["PAID_SEARCH", "EMAIL", "AFFILIATE", "SOCIAL"]), "touchpoint_at": updated.isoformat(), "cost_amount": round(rng.uniform(0.1, 20), 2)})
        elif name == "fraud_signal":
            row.update({"payment_transaction_id": i + 1, "reservation_id": reservation_id, "signal_type": rng.choice(["VELOCITY", "DEVICE", "LOCATION"]), "severity": rng.choice(["LOW", "MEDIUM", "HIGH"]), "signal_at": updated.isoformat()})
    return row


def generate_relational_exports(
    source: str,
    scale_name: str,
    output: Path,
    seed: int = DEFAULT_SEED,
    max_rows: int | None = None,
) -> dict[str, int]:
    tables = ORACLE_TABLES if source == "oracle" else POSTGRES_TABLES
    scale = get_scale(scale_name)
    source_dir = output / source
    source_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).replace(microsecond=0)
    counts: dict[str, int] = {}
    for index, table in enumerate(tables):
        count = target_rows(table, scale_name)
        if max_rows is not None:
            count = min(count, max_rows)
        rng = random.Random(seed + index)
        path = source_dir / f"{table}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for row_number in range(count):
                row = make_row(source, table, row_number, rng, now, scale.properties, scale.guests)
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        counts[table] = count
    (source_dir / "manifest.json").write_text(
        json.dumps({"source": source, "scale": scale_name, "seed": seed, "row_counts": counts}, indent=2) + "\n",
        encoding="utf-8",
    )
    return counts
