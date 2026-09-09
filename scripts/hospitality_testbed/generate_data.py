#!/usr/bin/env python3
"""Generate a deterministic, relational hospitality data ecosystem in bounded batches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from lib import FAIL, PASS, ROOT, evidence_path, load_yaml, sha256_file, update_state, write_json

TIMESTAMP_FIELDS = ("_at", "_ts")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=("tiny", "small", "medium", "large"), default="tiny")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--hotels", type=int)
    parser.add_argument("--guests", type=int)
    parser.add_argument("--reservations", type=int)
    parser.add_argument("--rows-per-file", type=int)
    parser.add_argument("--reference-date", default=None, help="ISO date used as the deterministic clock")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    return parser.parse_args()


def iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


class DatasetWriter:
    def __init__(self, root: Path, generation_id: str, load_id: str, entities: dict[str, Any]) -> None:
        self.root = root
        self.generation_id = generation_id
        self.load_id = load_id
        self.entities = entities
        self.files: list[dict[str, Any]] = []
        self.sequence: defaultdict[str, int] = defaultdict(int)

    def write(self, entity: str, rows: list[dict[str, Any]], partition_date: date | None = None) -> None:
        if not rows:
            return
        spec = self.entities[entity]
        self.sequence[entity] += 1
        extension = "csv" if spec["format"] == "csv" else "parquet"
        folder = self.root / spec["format"] / entity
        if partition_date:
            folder = folder / f"year={partition_date:%Y}" / f"month={partition_date:%m}"
            if spec["format"] == "csv":
                folder = folder / f"day={partition_date:%d}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{entity}_{self.sequence[entity]:05d}.{extension}"
        enriched = [{**row, "_load_id": self.load_id, "_generation_id": self.generation_id} for row in rows]
        columns = [*spec["columns"], "_load_id", "_generation_id"]
        if extension == "csv":
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                writer.writerows([{key: iso(row.get(key)) for key in columns} for row in enriched])
        else:
            try:
                import pyarrow as pa
                import pyarrow.parquet as pq
            except ImportError as exc:
                raise RuntimeError("Parquet generation requires pyarrow; install the testbed dependencies") from exc
            table = pa.Table.from_pylist([{key: row.get(key) for key in columns} for row in enriched])
            pq.write_table(table, path, compression="snappy", row_group_size=min(len(rows), 50_000))
        timestamps: list[str] = []
        for row in enriched:
            for key, value in row.items():
                if key.endswith(TIMESTAMP_FIELDS) or key.endswith("_date"):
                    if value is not None:
                        timestamps.append(str(iso(value)))
        self.files.append({
            "entity": entity,
            "file": path.relative_to(self.root).as_posix(),
            "format": spec["format"],
            "row_count": len(rows),
            "byte_count": path.stat().st_size,
            "min_timestamp": min(timestamps) if timestamps else None,
            "max_timestamp": max(timestamps) if timestamps else None,
            "schema": {**spec["columns"], "_load_id": "VARCHAR", "_generation_id": "VARCHAR"},
            "checksum": sha256_file(path),
            "expected_target": spec["target"],
        })


def chunks(values: Iterable[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def safe_clean(output: Path) -> None:
    resolved = output.resolve()
    if resolved in {Path("/").resolve(), Path.home().resolve(), ROOT.resolve()} or len(resolved.parts) < 3:
        raise ValueError(f"Refusing unsafe output directory: {resolved}")
    for name in ("csv", "parquet", "failures"):
        candidate = resolved / name
        if candidate.exists():
            shutil.rmtree(candidate)
    for name in ("manifest.json",):
        candidate = resolved / name
        if candidate.exists():
            candidate.unlink()
    resolved.mkdir(parents=True, exist_ok=True)


def build_dataset(settings: dict[str, Any], output: Path, *, record_runtime: bool = True) -> dict[str, Any]:
    seed = int(settings["seed"])
    rng = random.Random(seed)
    reference = date.fromisoformat(settings["reference_date"])
    generated_at = datetime.combine(reference, time(0), UTC).isoformat()
    fingerprint = json.dumps(settings, sort_keys=True).encode()
    generation_id = "gen_" + hashlib.sha256(fingerprint).hexdigest()[:16]
    load_id = "load_" + generation_id.removeprefix("gen_")
    ingestion = load_yaml("hospitality_ingestion.yml")["entities"]
    writer = DatasetWriter(output, generation_id, load_id, ingestion)
    safe_clean(output)

    brands = ("Aurora", "Harbor", "Summit", "Crescent")
    cities = (("New York", "NY", "US", "America/New_York"), ("Miami", "FL", "US", "America/New_York"), ("Denver", "CO", "US", "America/Denver"), ("Seattle", "WA", "US", "America/Los_Angeles"), ("Toronto", "ON", "CA", "America/Toronto"))
    room_types: list[dict[str, Any]] = []
    rooms: list[dict[str, Any]] = []
    rooms_by_hotel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    staff_by_hotel: dict[str, list[str]] = defaultdict(list)
    hotels: list[dict[str, Any]] = []
    for index in range(1, int(settings["hotels"]) + 1):
        hotel_id = f"H{index:04d}"
        city, state, country, timezone = cities[(index - 1) % len(cities)]
        room_count = 36 + (index * 7 % 45)
        hotels.append({"hotel_id": hotel_id, "hotel_name": f"{brands[index % len(brands)]} {city} {index}", "brand": brands[index % len(brands)], "city": city, "state": state, "country": country, "timezone": timezone, "opened_date": date(1995 + index % 25, 1 + index % 12, 1 + index % 20), "room_count": room_count, "active": True})
        type_ids = []
        for type_index, (name, occupancy, rate, bed) in enumerate((("STANDARD", 2, 139, "QUEEN"), ("DELUXE", 3, 219, "KING"), ("SUITE", 4, 349, "KING")), 1):
            room_type_id = f"RT{index:04d}{type_index}"
            type_ids.append(room_type_id)
            room_types.append({"room_type_id": room_type_id, "hotel_id": hotel_id, "type_name": name, "max_occupancy": occupancy, "base_rate": rate + index * 2, "bed_type": bed})
        for room_index in range(1, room_count + 1):
            room = {"room_id": f"R{index:04d}{room_index:04d}", "hotel_id": hotel_id, "room_type_id": type_ids[(room_index - 1) % 3], "room_number": f"{1 + room_index // 20}{room_index % 20:02d}", "floor_number": 1 + room_index // 20, "status": "ACTIVE" if room_index % 29 else "OUT_OF_SERVICE"}
            rooms.append(room)
            rooms_by_hotel[hotel_id].append(room)
        staff_rows = []
        for staff_index in range(1, 13):
            staff_id = f"S{index:04d}{staff_index:03d}"
            staff_by_hotel[hotel_id].append(staff_id)
            department = ("FRONT_DESK", "HOUSEKEEPING", "FOOD_BEVERAGE", "MAINTENANCE")[staff_index % 4]
            staff_rows.append({"staff_id": staff_id, "hotel_id": hotel_id, "department": department, "job_title": f"{department}_ASSOCIATE", "hired_date": reference - timedelta(days=365 + staff_index * 31), "active": True})
        writer.write("property_staff", staff_rows)
    writer.write("hotels", hotels)
    writer.write("room_types", room_types)
    for batch in chunks(rooms, int(settings["rows_per_file"])):
        writer.write("rooms", batch)

    guest_count = int(settings["guests"])
    first_names = ("Ava", "Noah", "Mia", "Liam", "Zoe", "Ethan", "Ivy", "Mateo")
    last_names = ("Patel", "Smith", "Garcia", "Kim", "Brown", "Singh", "Martin", "Chen")
    for start in range(1, guest_count + 1, int(settings["rows_per_file"])):
        guest_rows, loyalty_rows, preference_rows = [], [], []
        for index in range(start, min(guest_count + 1, start + int(settings["rows_per_file"]))):
            guest_id = f"G{index:09d}"
            guest_rows.append({"guest_id": guest_id, "first_name": first_names[index % len(first_names)], "last_name": last_names[(index * 3) % len(last_names)], "email": f"guest{index}@example.test", "country": ("US", "CA", "GB", "AU")[index % 4], "created_at": datetime.combine(reference - timedelta(days=index % 1800), time(12), UTC), "marketing_opt_in": index % 3 != 0})
            if index % 2 == 0:
                loyalty_rows.append({"loyalty_id": f"L{index:09d}", "guest_id": guest_id, "tier": ("MEMBER", "SILVER", "GOLD", "PLATINUM")[(index // 7) % 4], "points_balance": (index * 137) % 125000, "joined_date": reference - timedelta(days=index % 1500)})
            preference_rows.append({"preference_id": f"GP{index:09d}", "guest_id": guest_id, "preference_type": ("PILLOW", "FLOOR", "DIETARY")[index % 3], "preference_value": ("FEATHER_FREE", "HIGH", "VEGETARIAN")[index % 3], "updated_at": datetime.combine(reference - timedelta(days=index % 90), time(10), UTC)})
        writer.write("guests", guest_rows)
        writer.write("loyalty_members", loyalty_rows)
        writer.write("guest_preferences", preference_rows, reference)

    channels = ("DIRECT_WEB", "MOBILE", "EXPEDIA", "BOOKING", "CORPORATE")
    statuses = ("CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")
    reservation_count = int(settings["reservations"])
    batch_size = int(settings["rows_per_file"])
    for start in range(1, reservation_count + 1, batch_size):
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # Landing partitions represent the deterministic ingestion date; event timestamps
        # remain independently distributed across their realistic business windows.
        partition_day = reference
        for index in range(start, min(reservation_count + 1, start + batch_size)):
            hotel = hotels[rng.randrange(len(hotels))]
            room = rng.choice(rooms_by_hotel[hotel["hotel_id"]])
            guest_id = f"G{rng.randint(1, guest_count):09d}"
            checkin = reference + timedelta(days=rng.randint(-180, 180))
            nights = rng.randint(1, 8)
            checkout = checkin + timedelta(days=nights)
            booked_at = datetime.combine(checkin - timedelta(days=rng.randint(1, 180)), time(rng.randrange(24), rng.randrange(60)), UTC)
            status = rng.choices(statuses, weights=(35, 45, 15, 5), k=1)[0]
            if checkin > reference and status == "COMPLETED":
                status = "CONFIRMED"
            channel = channels[index % len(channels)]
            seasonal = 1.0 + 0.20 * (1 if checkin.month in {6, 7, 8, 12} else -0.25)
            base_rate = next(item["base_rate"] for item in room_types if item["room_type_id"] == room["room_type_id"])
            total = round(float(base_rate) * seasonal * nights, 2)
            reservation_id = f"RSV{index:010d}"
            updated_at = booked_at + timedelta(hours=rng.randint(1, 48))
            buckets["reservations"].append({"reservation_id": reservation_id, "hotel_id": hotel["hotel_id"], "guest_id": guest_id, "room_id": room["room_id"], "channel_id": channel, "booking_status": status, "booked_at": booked_at, "checkin_date": checkin, "checkout_date": checkout, "adults": rng.randint(1, 2), "children": rng.randint(0, 2), "currency": "USD" if hotel["country"] == "US" else "CAD", "total_amount": total, "updated_at": updated_at})
            buckets["reservation_guests"].append({"reservation_guest_id": f"RG{index:010d}P", "reservation_id": reservation_id, "guest_id": guest_id, "is_primary": True})
            payment_id = f"PAY{index:010d}"
            paid_ratio = 1.0 if index % 7 else 0.5
            payment_status = "REFUNDED" if status == "CANCELLED" and index % 3 == 0 else ("PARTIAL" if paid_ratio < 1 else "CAPTURED")
            buckets["payments"].append({"payment_id": payment_id, "reservation_id": reservation_id, "payment_ts": booked_at + timedelta(minutes=10), "payment_method": ("CARD", "WALLET", "BANK_TRANSFER")[index % 3], "payment_status": payment_status, "amount": round(total * paid_ratio, 2), "currency": "USD" if hotel["country"] == "US" else "CAD"})
            buckets["channel_bookings"].append({"channel_booking_id": f"CB{index:010d}", "reservation_id": reservation_id, "channel_id": channel, "channel_reference": f"{channel}-{index:010d}", "commission_amount": round(total * (0.15 if channel in {"EXPEDIA", "BOOKING"} else 0), 2), "booked_at": booked_at})
            for event_index, event_type in enumerate(("SEARCH", "CHECKOUT_STARTED", "BOOKED"), 1):
                buckets["web_booking_events"].append({"event_id": f"WEB{index:010d}{event_index}", "session_id": f"SES{index:010d}", "guest_id": guest_id, "reservation_id": reservation_id if event_type == "BOOKED" else None, "event_type": event_type, "event_ts": booked_at - timedelta(minutes=12 - event_index * 4), "channel_id": channel})
            if status == "CANCELLED":
                cancelled_at = min(datetime.combine(checkin, time(0), UTC) - timedelta(hours=12), updated_at)
                buckets["cancellations"].append({"cancellation_id": f"CAN{index:010d}", "reservation_id": reservation_id, "cancelled_at": cancelled_at, "reason": ("PLANS_CHANGED", "PRICE", "DUPLICATE")[index % 3], "fee_amount": round(total * (0.1 if (checkin - cancelled_at.date()).days < 2 else 0), 2)})
                if payment_status == "REFUNDED":
                    buckets["refunds"].append({"refund_id": f"REF{index:010d}", "payment_id": payment_id, "reservation_id": reservation_id, "refund_ts": cancelled_at + timedelta(hours=2), "amount": round(total * paid_ratio, 2), "reason": "CANCELLATION"})
            if status == "COMPLETED" and checkout <= reference:
                checkin_at = datetime.combine(checkin, time(15), UTC) + timedelta(minutes=rng.randint(-30, 120))
                checkout_at = datetime.combine(checkout, time(11), UTC) + timedelta(minutes=rng.randint(-30, 90))
                buckets["stays"].append({"stay_id": f"STY{index:010d}", "reservation_id": reservation_id, "hotel_id": hotel["hotel_id"], "room_id": room["room_id"], "actual_checkin_at": checkin_at, "actual_checkout_at": checkout_at, "stay_status": "COMPLETED"})
                buckets["folio_charges"].extend([
                    {"folio_id": f"FOL{index:010d}R", "reservation_id": reservation_id, "charge_ts": checkin_at, "charge_type": "ROOM", "description": "Room and tax", "amount": total, "currency": "USD" if hotel["country"] == "US" else "CAD"},
                    {"folio_id": f"FOL{index:010d}X", "reservation_id": reservation_id, "charge_ts": checkout_at - timedelta(hours=6), "charge_type": "INCIDENTAL", "description": "Guest incidentals", "amount": round(15 + (index % 80), 2), "currency": "USD" if hotel["country"] == "US" else "CAD"},
                ])
                buckets["housekeeping_events"].append({"event_id": f"HK{index:010d}", "hotel_id": hotel["hotel_id"], "room_id": room["room_id"], "event_type": "ROOM_CLEANED", "event_ts": checkout_at + timedelta(minutes=20), "staff_id": staff_by_hotel[hotel["hotel_id"]][index % 12], "duration_minutes": 20 + index % 36})
        for entity, rows in buckets.items():
            writer.write(entity, rows, partition_day)

    inventory_rows, rate_rows, metric_rows = [], [], []
    for offset in range(-30, 61):
        metric_date = reference + timedelta(days=offset)
        season = 0.72 + (0.16 if metric_date.month in {6, 7, 8, 12} else 0)
        for hotel in hotels:
            hotel_available = 0
            hotel_occupied = 0
            for room_type in (item for item in room_types if item["hotel_id"] == hotel["hotel_id"]):
                count = sum(1 for room in rooms_by_hotel[hotel["hotel_id"]] if room["room_type_id"] == room_type["room_type_id"] and room["status"] == "ACTIVE")
                occupied = min(count, int(count * season * (0.92 + rng.random() * 0.16)))
                hotel_available += count
                hotel_occupied += occupied
                inventory_rows.append({"inventory_id": f"INV-{hotel['hotel_id']}-{room_type['room_type_id']}-{metric_date:%Y%m%d}", "hotel_id": hotel["hotel_id"], "room_type_id": room_type["room_type_id"], "inventory_date": metric_date, "available_rooms": count, "occupied_rooms": occupied, "out_of_service_rooms": sum(1 for room in rooms_by_hotel[hotel["hotel_id"]] if room["room_type_id"] == room_type["room_type_id"] and room["status"] != "ACTIVE")})
                for plan, multiplier in (("FLEX", 1.0), ("ADVANCE", 0.88), ("REFUNDABLE", 1.12)):
                    rate_rows.append({"rate_id": f"RATE-{hotel['hotel_id']}-{room_type['room_type_id']}-{metric_date:%Y%m%d}-{plan}", "hotel_id": hotel["hotel_id"], "room_type_id": room_type["room_type_id"], "rate_date": metric_date, "rate_plan": plan, "nightly_rate": round(float(room_type["base_rate"]) * multiplier * (1.18 if metric_date.month in {6, 7, 8, 12} else 0.96), 2), "currency": "USD" if hotel["country"] == "US" else "CAD"})
            gross = round(hotel_occupied * (155 + hotel_occupied % 90), 2)
            metric_rows.append({"metric_id": f"MET-{hotel['hotel_id']}-{metric_date:%Y%m%d}", "hotel_id": hotel["hotel_id"], "metric_date": metric_date, "available_rooms": hotel_available, "occupied_rooms": hotel_occupied, "gross_revenue": gross, "cancellations": hotel_occupied % 7})
        if len(inventory_rows) >= batch_size:
            writer.write("room_inventory", inventory_rows, reference)
            writer.write("daily_rates", rate_rows, reference)
            writer.write("property_daily_metrics", metric_rows, reference)
            inventory_rows, rate_rows, metric_rows = [], [], []
    writer.write("room_inventory", inventory_rows, reference)
    writer.write("daily_rates", rate_rows, reference)
    writer.write("property_daily_metrics", metric_rows, reference)

    manifest = {
        "version": 1,
        "generation_id": generation_id,
        "load_id": load_id,
        "seed": seed,
        "generated_at": generated_at,
        "settings": settings,
        "file_count": len(writer.files),
        "row_count": sum(item["row_count"] for item in writer.files),
        "entities": sorted(ingestion),
        "files": writer.files,
    }
    write_json(output / "manifest.json", manifest)
    if record_runtime:
        write_json(evidence_path("generation-manifest.json"), manifest)
        update_state(generation_id=generation_id, load_id=load_id, mode="generated", started_at=generated_at, files_generated=len(writer.files))
    return {"status": PASS, **manifest}


def main() -> int:
    args = parse_args()
    config = load_yaml("hospitality_testbed.yml")
    settings = {**config["defaults"], **config["presets"][args.preset], "preset": args.preset}
    for key in ("seed", "hotels", "guests", "reservations", "rows_per_file"):
        value = getattr(args, key)
        if value is not None:
            settings[key] = value
    if args.reference_date:
        settings["reference_date"] = args.reference_date
    output = (args.output or ROOT / settings["output"]).resolve()
    try:
        result = build_dataset(settings, output)
    except Exception as exc:
        result = {"status": FAIL, "error": str(exc), "output": str(output)}
    destination = args.json_output or evidence_path("generation.json")
    write_json(destination, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
