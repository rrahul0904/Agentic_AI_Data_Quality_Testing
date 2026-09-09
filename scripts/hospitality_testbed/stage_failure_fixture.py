#!/usr/bin/env python3
"""Generate isolated failure fixtures; stage one only with explicit mutation approval."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from lib import BLOCKED_APPROVAL, BLOCKED_EXTERNAL, FAIL, PASS, ROOT, approved, env, evidence_path, load_yaml, snowflake_connect, testbed_database, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=tuple(load_yaml("hospitality_failure_scenarios.yml")["scenarios"]))
    parser.add_argument("--all", action="store_true", help="Generate all fixtures")
    parser.add_argument("--stage", action="store_true", help="Stage the selected fixture; never implied")
    parser.add_argument("--mode", choices=("local", "live"), default="local")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "hospitality" / "failures")
    parser.add_argument("--json-output", type=Path, default=evidence_path("failure-fixtures.json"))
    return parser.parse_args()


HEADER = ["reservation_id", "hotel_id", "guest_id", "room_id", "channel_id", "booking_status", "booked_at", "checkin_date", "checkout_date", "adults", "children", "currency", "total_amount", "updated_at", "_load_id", "_generation_id"]
GOOD = ["RSV_FAILURE_001", "H0001", "G000000001", "R00010001", "DIRECT_WEB", "CONFIRMED", "2026-08-01T12:00:00+00:00", "2026-09-10", "2026-09-12", "2", "0", "USD", "350.00", "2026-08-01T12:05:00+00:00", "load_failure", "gen_failure"]


def write_csv(path: Path, header: list[str], rows: list[list[str]], delimiter: str = ",") -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def generate(root: Path, selected: list[str]) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    scenarios = load_yaml("hospitality_failure_scenarios.yml")["scenarios"]
    produced = []
    for scenario in selected:
        folder = root / scenario
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        path = folder / f"reservation_{scenario}.csv"
        if scenario == "malformed_csv":
            path.write_text(",".join(HEADER) + "\n\"unclosed,field\n", encoding="utf-8")
        elif scenario == "invalid_timestamp":
            row = GOOD.copy(); row[6] = "not-a-timestamp"; write_csv(path, HEADER, [row])
        elif scenario == "bad_number":
            row = GOOD.copy(); row[12] = "not-a-number"; write_csv(path, HEADER, [row])
        elif scenario == "missing_required_column":
            write_csv(path, HEADER[1:], [GOOD[1:]])
        elif scenario in {"extra_source_column", "schema_drift"}:
            write_csv(path, HEADER + ["unexpected_v2_column"], [GOOD + ["drift"]])
        elif scenario == "null_required":
            row = GOOD.copy(); row[0] = ""; write_csv(path, HEADER, [row])
        elif scenario == "duplicate_key":
            write_csv(path, HEADER, [GOOD, GOOD])
        elif scenario == "zero_byte_file":
            path.write_bytes(b"")
        elif scenario == "corrupt_parquet":
            path = folder / "stays_corrupt.parquet"; path.write_bytes(b"PAR1-corrupt-not-parquet")
        elif scenario == "wrong_delimiter":
            write_csv(path, HEADER, [GOOD], delimiter="|")
        elif scenario == "wrong_header":
            write_csv(path, [item.upper() + "_WRONG" for item in HEADER], [GOOD])
        elif scenario == "stale_file":
            write_csv(path, HEADER, [GOOD]); os.utime(path, (1_577_836_800, 1_577_836_800))
        elif scenario == "unexpected_extension":
            path = folder / "reservation.txt"; write_csv(path, HEADER, [GOOD])
        elif scenario == "missing_file_batch":
            path = folder / "EXPECTED_BUT_NOT_DELIVERED.csv"
        elif scenario == "partial_batch":
            write_csv(path, HEADER, [GOOD])
        elif scenario == "duplicate_file_delivery":
            write_csv(path, HEADER, [GOOD]); shutil.copy2(path, folder / "reservation_duplicate_delivery_copy.csv")
        elif scenario == "late_arriving_file":
            write_csv(path, HEADER, [GOOD]); os.utime(path, (1_735_689_600, 1_735_689_600))
        produced.append({"scenario": scenario, "expected_divergence": scenarios[scenario]["expected_divergence"], "files": [item.name for item in sorted(folder.iterdir())]})
    produced_by_name = {item["scenario"]: item for item in produced}
    scenario_records = []
    for scenario, spec in scenarios.items():
        if scenario in produced_by_name:
            scenario_records.append(produced_by_name[scenario])
            continue
        folder = root / scenario
        scenario_records.append(
            {
                "scenario": scenario,
                "expected_divergence": spec["expected_divergence"],
                "files": [item.name for item in sorted(folder.iterdir())] if folder.exists() else [],
            }
        )
    ground_truth = {"status": PASS, "generated_at": datetime.now(UTC).isoformat(), "scenarios": scenario_records}
    write_json(root / "ground_truth.json", ground_truth)
    return ground_truth


def stage_fixture(root: Path, scenario: str, mode: str) -> dict[str, object]:
    if not approved():
        return {"status": BLOCKED_APPROVAL, "scenario": scenario, "message": "Set ADE_TESTBED_MUTATION_APPROVED=true before staging bad data"}
    files = [path for path in (root / scenario).iterdir() if path.is_file()]
    if not files:
        return {"status": FAIL, "scenario": scenario, "error": "Scenario has no physical file to stage"}
    failure_run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    staged_paths = []
    if mode == "live":
        if not env("ADE_TESTBED_S3_BUCKET") or not env("AWS_REGION"):
            return {"status": BLOCKED_EXTERNAL, "scenario": scenario, "error": "AWS configuration is missing"}
        import boto3
        client = boto3.client("s3", region_name=env("AWS_REGION"))
        prefix = (env("ADE_TESTBED_S3_PREFIX", "hospitality") or "hospitality").strip("/")
        for path in files:
            entity_prefix = "parquet/stays" if path.suffix == ".parquet" else "csv/reservations"
            object_path = f"{entity_prefix}/failures/{scenario}/{failure_run_id}/{path.name}"
            client.upload_file(
                str(path),
                env("ADE_TESTBED_S3_BUCKET"),
                f"{prefix}/{object_path}",
            )
            staged_paths.append(object_path)
    else:
        connection = snowflake_connect()
        with connection:
            cursor = connection.cursor()
            for path in files:
                escaped = str(path.resolve()).replace("'", "''")
                entity_prefix = "parquet/stays" if path.suffix == ".parquet" else "csv/reservations"
                cursor.execute(
                    f"PUT 'file://{escaped}' @{testbed_database(mutation=True)}.RAW.STAGE_HOSPITALITY_INTERNAL/"
                    f"{entity_prefix}/failures/{scenario}/{failure_run_id}/ AUTO_COMPRESS=FALSE OVERWRITE=FALSE"
                )
                staged_paths.append(f"{entity_prefix}/failures/{scenario}/{failure_run_id}/{path.name}")
            cursor.close()
    return {
        "status": PASS,
        "scenario": scenario,
        "mode": mode,
        "failure_run_id": failure_run_id,
        "files_staged": len(files),
        "staged_paths": staged_paths,
        "testbed_only": True,
    }


def main() -> int:
    args = parse_args()
    if not args.all and not args.scenario:
        raise SystemExit("Choose --all or --scenario")
    selected = list(load_yaml("hospitality_failure_scenarios.yml")["scenarios"]) if args.all else [args.scenario]
    try:
        result = generate(args.output, selected)
        if args.stage:
            if len(selected) != 1:
                result = {"status": FAIL, "error": "--stage requires exactly one --scenario"}
            else:
                result = stage_fixture(args.output, selected[0], args.mode)
    except RuntimeError as exc:
        result = {"status": BLOCKED_EXTERNAL, "error": str(exc)}
    except Exception as exc:
        result = {"status": FAIL, "error": str(exc)}
    write_json(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
