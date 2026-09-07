#!/usr/bin/env python3
"""Generate deterministic, multi-GB-capable file feeds without retaining rows in memory."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_generator.faker_config import BAD_RECORD_RATE, DEFAULT_SEED, DUPLICATE_RATE, LATE_ARRIVAL_RATE, get_scale

RowFactory = Callable[[int, random.Random, datetime], dict[str, Any]]


def common(i: int, now: datetime, filename: str, source_system: str = "local_files") -> dict[str, Any]:
    event_time = now - timedelta(minutes=i % (60 * 24 * 120))
    return {
        "load_date": now.date().isoformat(),
        "source_file_name": filename,
        "source_system": source_system,
        "event_timestamp": event_time.isoformat(),
    }


def clickstream(i: int, rng: random.Random, now: datetime) -> dict[str, Any]:
    row = common(i, now, "clickstream_events.jsonl")
    row.update(
        event_id=f"web-{i:012d}",
        anonymous_id=f"anon-{rng.randrange(1, 200_000):08d}",
        session_id=f"session-{i // rng.randint(3, 12):010d}",
        event_name=rng.choice(["search", "property_view", "room_view", "add_to_cart", "checkout"]),
        property_id=f"P{rng.randrange(1, 501):05d}",
        channel=rng.choice(["organic", "paid_search", "affiliate", "email", "direct"]),
        page_url=f"https://example.invalid/properties/P{rng.randrange(1, 501):05d}",
    )
    return row


def mobile(i: int, rng: random.Random, now: datetime) -> dict[str, Any]:
    row = common(i, now, "mobile_events.jsonl")
    row.update(
        event_id=f"mobile-{i:012d}", user_id=f"U{rng.randrange(1, 1_000_001):09d}",
        device_id=f"D{rng.randrange(1, 400_000):09d}", platform=rng.choice(["ios", "android"]),
        app_version=rng.choice(["7.2.0", "7.3.0", "7.3.1"]),
        event_name=rng.choice(["app_open", "search", "view_rate", "book", "cancel"]),
    )
    return row


def partner_booking(i: int, rng: random.Random, now: datetime) -> dict[str, Any]:
    row = common(i, now, "partner_bookings.csv", "channel_partner")
    nights = rng.randint(1, 8)
    check_in = now.date() + timedelta(days=rng.randint(-30, 180))
    row.update(
        partner_booking_id=f"PB{i:011d}", partner_id=f"PARTNER-{rng.randrange(1, 40):03d}",
        property_id=f"P{rng.randrange(1, 501):05d}", status=rng.choice(["confirmed", "confirmed", "cancelled"]),
        check_in_date=check_in.isoformat(), check_out_date=(check_in + timedelta(days=nights)).isoformat(),
        currency="USD", gross_amount=f"{rng.uniform(100, 5000):.2f}", commission_amount=f"{rng.uniform(10, 800):.2f}",
    )
    return row


def rate(i: int, rng: random.Random, now: datetime) -> dict[str, Any]:
    row = common(i, now, "third_party_rates.csv", "rate_shop")
    stay_date = now.date() + timedelta(days=i % 365)
    row.update(
        rate_shop_id=f"RS{i:012d}", property_id=f"P{rng.randrange(1, 501):05d}",
        competitor_property_id=f"CP{rng.randrange(1, 1001):06d}", room_type=rng.choice(["KING", "QUEEN", "SUITE"]),
        stay_date=stay_date.isoformat(), currency="USD", observed_rate=f"{rng.uniform(80, 900):.2f}",
        available=rng.choice([True, True, True, False]),
    )
    return row


def settlement(i: int, rng: random.Random, now: datetime) -> dict[str, Any]:
    row = common(i, now, "payment_gateway_settlements.csv", "payment_gateway")
    gross = round(rng.uniform(25, 7000), 2)
    fee = round(gross * rng.uniform(0.018, 0.035), 2)
    row.update(
        settlement_id=f"SET{i:012d}", transaction_id=f"TX{i:012d}", gateway=rng.choice(["stripe_sim", "adyen_sim"]),
        settlement_date=(now.date() - timedelta(days=i % 45)).isoformat(), currency="USD",
        gross_amount=f"{gross:.2f}", fee_amount=f"{fee:.2f}", net_amount=f"{gross - fee:.2f}",
        status=rng.choice(["settled", "settled", "held"]),
    )
    return row


def generic_factory(filename: str, domain: str, event_names: list[str]) -> RowFactory:
    def build(i: int, rng: random.Random, now: datetime) -> dict[str, Any]:
        row = common(i, now, filename, domain)
        row.update(
            record_id=f"{domain[:5].upper()}-{i:012d}", property_id=f"P{rng.randrange(1, 501):05d}",
            guest_id=f"G{rng.randrange(1, 1_000_001):09d}", event_type=rng.choice(event_names),
            status=rng.choice(["completed", "completed", "pending", "failed"]),
            amount=f"{rng.uniform(0, 1200):.2f}", notes=None if rng.random() < 0.25 else "synthetic",
        )
        return row

    return build


FEEDS: dict[str, tuple[str, float, RowFactory]] = {
    "clickstream_events.jsonl": ("jsonl", 1.0, clickstream),
    "mobile_events.jsonl": ("jsonl", 0.5, mobile),
    "partner_bookings.csv": ("csv", 0.08, partner_booking),
    "third_party_rates.csv": ("csv", 0.3, rate),
    "payment_gateway_settlements.csv": ("csv", 0.05, settlement),
    "call_center_interactions.csv": ("csv", 0.05, generic_factory("call_center_interactions.csv", "call_center", ["inquiry", "change", "cancel"])),
    "guest_review_exports.csv": ("csv", 0.05, generic_factory("guest_review_exports.csv", "review_export", ["review", "response"])),
    "property_image_metadata.json": ("jsonl", 0.02, generic_factory("property_image_metadata.json", "media", ["uploaded", "approved", "retired"])),
    "inventory_adjustments.csv": ("csv", 0.08, generic_factory("inventory_adjustments.csv", "inventory", ["add", "remove", "out_of_service"])),
    "email_marketing_events.csv": ("csv", 0.4, generic_factory("email_marketing_events.csv", "marketing", ["sent", "open", "click", "unsubscribe"])),
    "loyalty_partner_transactions.csv": ("csv", 0.08, generic_factory("loyalty_partner_transactions.csv", "loyalty_partner", ["earn", "redeem", "expire"])),
    "weather_by_property.csv": ("csv", 0.04, generic_factory("weather_by_property.csv", "weather", ["observation", "forecast"])),
    "local_events_calendar.csv": ("csv", 0.01, generic_factory("local_events_calendar.csv", "local_events", ["conference", "concert", "sports"])),
    "competitor_rate_shops.parquet": ("parquet", 0.2, rate),
    "restaurant_pos_transactions.csv": ("csv", 0.15, generic_factory("restaurant_pos_transactions.csv", "restaurant_pos", ["sale", "void", "refund"])),
    "spa_pos_transactions.csv": ("csv", 0.05, generic_factory("spa_pos_transactions.csv", "spa_pos", ["service", "retail", "refund"])),
    "maintenance_sensor_events.jsonl": ("jsonl", 0.3, generic_factory("maintenance_sensor_events.jsonl", "iot_sensor", ["reading", "warning", "critical"])),
    "housekeeping_inspection_scores.csv": ("csv", 0.08, generic_factory("housekeeping_inspection_scores.csv", "housekeeping", ["inspection", "reinspection"])),
}


def dirty_rows(rows: Iterable[dict[str, Any]], rng: random.Random) -> Iterable[dict[str, Any]]:
    previous: dict[str, Any] | None = None
    for row in rows:
        if rng.random() < BAD_RECORD_RATE:
            row = dict(row)
            row["event_timestamp"] = "not-a-timestamp"
            if "property_id" in row:
                row["property_id"] = None
        elif rng.random() < LATE_ARRIVAL_RATE:
            row = dict(row)
            row["event_timestamp"] = (datetime.now(UTC) - timedelta(days=400)).isoformat()
        yield row
        if previous is not None and rng.random() < DUPLICATE_RATE:
            yield dict(previous)
        previous = row


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
            count += 1
    return count


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    iterator = iter(rows)
    try:
        first = next(iterator)
    except StopIteration:
        return 0
    count = 1
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(first))
        writer.writeheader()
        writer.writerow(first)
        for row in iterator:
            writer.writerow(row)
            count += 1
    return count


def write_parquet(path: Path, rows: Iterable[dict[str, Any]], chunk_size: int) -> int:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Parquet generation requires: pip install -e '.[parquet]'") from exc
    writer = None
    count = 0
    batch: list[dict[str, Any]] = []
    try:
        for row in rows:
            batch.append(row)
            if len(batch) >= chunk_size:
                table = pa.Table.from_pylist(batch)
                writer = writer or pq.ParquetWriter(path, table.schema, compression="snappy")
                writer.write_table(table)
                count += len(batch)
                batch.clear()
        if batch:
            table = pa.Table.from_pylist(batch)
            writer = writer or pq.ParquetWriter(path, table.schema, compression="snappy")
            writer.write_table(table)
            count += len(batch)
    finally:
        if writer:
            writer.close()
    return count


def generate(scale_name: str, output: Path, seed: int, max_rows: int | None = None) -> dict[str, int]:
    scale = get_scale(scale_name)
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).replace(microsecond=0)
    counts: dict[str, int] = {}
    for feed_index, (filename, (kind, fraction, factory)) in enumerate(FEEDS.items()):
        target_count = max(1, int(scale.events * fraction))
        if max_rows is not None:
            target_count = min(target_count, max_rows)
        rng = random.Random(seed + feed_index)
        rows = (factory(i, rng, now) for i in range(target_count))
        rows = dirty_rows(rows, rng)
        path = output / filename
        if kind == "csv":
            counts[filename] = write_csv(path, rows)
        elif kind == "jsonl":
            counts[filename] = write_jsonl(path, rows)
        else:
            counts[filename] = write_parquet(path, rows, scale.chunk_size)
    manifest = {
        "generated_at": now.isoformat(), "scale": scale_name, "seed": seed,
        "intentional_quality_cases": {
            "bad_record_rate": BAD_RECORD_RATE, "duplicate_rate": DUPLICATE_RATE,
            "late_arrival_rate": LATE_ARRIVAL_RATE,
        },
        "row_counts": counts,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=["small", "medium", "large"], default="small")
    parser.add_argument("--output", type=Path, default=Path("sources/files/generated"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-rows", type=int, help="Per-feed cap for smoke tests; scale runs should omit this")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = generate(args.scale, args.output, args.seed, args.max_rows)
    print(json.dumps(result, indent=2))
