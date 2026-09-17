#!/usr/bin/env python3
"""Generate deterministic, relational synthetic Life & Health reinsurance data.

The output contains synthetic data only. It is intentionally not modeled on any
real person's data or any proprietary RGA dataset.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "rga_domain.yml"
DEFAULT_OUTPUT = ROOT / "artifacts" / "rga_testbed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", default="tiny", choices=("tiny", "small", "medium", "large", "stress"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reference-date", default="2026-09-01")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--policies", type=int, help="Override policy count for development/testing")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if config.get("domain") != "rga_life_health_reinsurance":
        raise ValueError("Unexpected RGA domain configuration")
    return config


def chunks(values: Iterable[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Writer:
    def __init__(self, output: Path, config: dict[str, Any], generation_id: str) -> None:
        self.output = output
        self.config = config
        self.generation_id = generation_id
        self.sequence: defaultdict[str, int] = defaultdict(int)
        self.files: list[dict[str, Any]] = []
        self.counts: defaultdict[str, int] = defaultdict(int)

    def write(self, entity: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        spec = self.config["entities"][entity]
        self.sequence[entity] += 1
        folder = self.output / "csv" / entity
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{entity}_{self.sequence[entity]:05d}.csv"
        columns = list(spec["columns"]) + ["_generation_id"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                payload = {key: row.get(key) for key in spec["columns"]}
                payload["_generation_id"] = self.generation_id
                writer.writerow({key: _serialize(value) for key, value in payload.items()})
        self.counts[entity] += len(rows)
        self.files.append(
            {
                "entity": entity,
                "file": path.relative_to(self.output).as_posix(),
                "row_count": len(rows),
                "byte_count": path.stat().st_size,
                "checksum": sha256(path),
                "target": spec["target"],
            }
        )


def _serialize(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _clean_output(output: Path) -> None:
    resolved = output.resolve()
    if resolved == Path("/") or len(resolved.parts) < 3:
        raise ValueError(f"Refusing unsafe output path {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def build_dataset(
    config: dict[str, Any],
    preset_name: str,
    seed: int,
    reference_date: date,
    output: Path,
    policy_override: int | None = None,
) -> dict[str, Any]:
    preset = dict(config["presets"][preset_name])
    if policy_override is not None:
        if policy_override <= 0:
            raise ValueError("policy override must be positive")
        preset["policies"] = policy_override
    _clean_output(output)
    fingerprint = json.dumps(
        {"preset": preset_name, "seed": seed, "reference_date": reference_date.isoformat(), **preset},
        sort_keys=True,
    )
    generation_id = "rga_" + hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
    rng = random.Random(seed)
    writer = Writer(output, config, generation_id)
    rows_per_file = int(preset["rows_per_file"])

    currencies = (("US", "USD"), ("CA", "CAD"), ("GB", "GBP"), ("AU", "AUD"))
    segments = ("LIFE", "LIVING_BENEFITS", "GROUP", "HEALTH")
    cedants: list[dict[str, Any]] = []
    for idx in range(1, int(preset["cedants"]) + 1):
        country, currency = currencies[(idx - 1) % len(currencies)]
        cedants.append(
            {
                "cedant_id": f"CED{idx:04d}",
                "cedant_name": f"Synthetic Cedant {idx:04d}",
                "country_code": country,
                "currency_code": currency,
                "market_segment": segments[idx % len(segments)],
                "active": True,
            }
        )
    writer.write("cedants", cedants)

    treaty_types = ("YRT", "COINSURANCE", "MODCO", "EXCESS_OF_LOSS")
    treaties: list[dict[str, Any]] = []
    for idx in range(1, int(preset["treaties"]) + 1):
        cedant = cedants[(idx - 1) % len(cedants)]
        effective = date(2018 + idx % 7, 1 + idx % 12, 1)
        treaties.append(
            {
                "treaty_id": f"TRT{idx:06d}",
                "cedant_id": cedant["cedant_id"],
                "treaty_name": f"Synthetic {treaty_types[idx % len(treaty_types)]} Treaty {idx:06d}",
                "treaty_type": treaty_types[idx % len(treaty_types)],
                "effective_date": effective,
                "expiry_date": date(2035, 12, 31),
                "retention_amount": float((idx % 10 + 1) * 100000),
                "ceded_share_pct": round(0.25 + (idx % 6) * 0.10, 4),
                "currency_code": cedant["currency_code"],
                "status": "ACTIVE",
            }
        )
    writer.write("treaties", treaties)

    product_specs = (
        ("TERM_LIFE", "LIFE", "DEATH_BENEFIT"),
        ("WHOLE_LIFE", "LIFE", "DEATH_BENEFIT"),
        ("CRITICAL_ILLNESS", "LIVING_BENEFITS", "LUMP_SUM"),
        ("DISABILITY_INCOME", "LIVING_BENEFITS", "MONTHLY_BENEFIT"),
    )
    products = [
        {
            "product_id": f"PRD{idx:03d}",
            "product_name": f"Synthetic {name.replace('_', ' ').title()}",
            "product_type": product_type,
            "benefit_basis": basis,
            "currency_code": "MULTI",
        }
        for idx, (name, product_type, basis) in enumerate(product_specs, 1)
    ]
    writer.write("products", products)

    policy_count = int(preset["policies"])
    policy_cache: list[dict[str, Any]] = []
    life_cache: list[dict[str, Any]] = []
    for start in range(1, policy_count + 1, rows_per_file):
        lives: list[dict[str, Any]] = []
        policies: list[dict[str, Any]] = []
        coverages: list[dict[str, Any]] = []
        underwriting: list[dict[str, Any]] = []
        premiums: list[dict[str, Any]] = []
        exposure: list[dict[str, Any]] = []
        end = min(policy_count + 1, start + rows_per_file)
        for idx in range(start, end):
            treaty = treaties[(idx * 7) % len(treaties)]
            cedant = next(item for item in cedants if item["cedant_id"] == treaty["cedant_id"])
            product = products[(idx - 1) % len(products)]
            insured_id = f"INS{idx:012d}"
            age = 18 + (idx * 13) % 63
            birth = reference_date - timedelta(days=int(age * 365.2425 + idx % 365))
            smoker = idx % 7 == 0
            bmi = round(19.0 + (idx * 17 % 150) / 10.0, 2)
            lives.append(
                {
                    "insured_id": insured_id,
                    "synthetic_name": f"Synthetic Life {idx:012d}",
                    "birth_date": birth,
                    "sex_code": "F" if idx % 2 else "M",
                    "country_code": cedant["country_code"],
                    "smoker_flag": smoker,
                    "bmi": bmi,
                }
            )
            issue_date = reference_date - timedelta(days=180 + (idx * 29) % 3650)
            status = "ACTIVE" if idx % 11 else ("LAPSED" if idx % 3 else "CLAIMED")
            sum_assured = float((50_000, 100_000, 250_000, 500_000, 1_000_000)[idx % 5])
            mortality_factor = 0.0008 + max(age - 35, 0) * 0.00005 + (0.0012 if smoker else 0)
            annual_premium = round(sum_assured * mortality_factor * (1.0 + max(bmi - 30, 0) * 0.02), 2)
            policy_id = f"POL{idx:012d}"
            policy = {
                "policy_id": policy_id,
                "treaty_id": treaty["treaty_id"],
                "cedant_id": cedant["cedant_id"],
                "product_id": product["product_id"],
                "insured_id": insured_id,
                "issue_date": issue_date,
                "policy_status": status,
                "sum_assured": sum_assured,
                "annual_premium": annual_premium,
                "currency_code": cedant["currency_code"],
            }
            policies.append(policy)
            coverages.append(
                {
                    "coverage_id": f"COV{idx:012d}A",
                    "policy_id": policy_id,
                    "coverage_type": product["product_type"],
                    "benefit_amount": sum_assured,
                    "effective_date": issue_date,
                    "expiry_date": issue_date + timedelta(days=365 * (20 if product["product_type"] == "LIFE" else 10)),
                }
            )
            risk_score = round(age * 0.55 + bmi * 0.75 + (18 if smoker else 0), 3)
            decision = "DECLINED" if risk_score > 75 else ("RATED" if risk_score > 55 else "STANDARD")
            underwriting.append(
                {
                    "underwriting_case_id": f"UW{idx:012d}",
                    "policy_id": policy_id,
                    "insured_id": insured_id,
                    "decision_date": issue_date - timedelta(days=7 + idx % 21),
                    "risk_class": "HIGH" if risk_score > 65 else ("MODERATE" if risk_score > 45 else "PREFERRED"),
                    "decision": decision,
                    "risk_score": risk_score,
                }
            )
            ceded_share = float(treaty["ceded_share_pct"])
            years_inforce = max(1, min(5, (reference_date - issue_date).days // 365 + 1))
            for year_offset in range(years_inforce):
                accounting_date = min(issue_date + timedelta(days=365 * year_offset), reference_date)
                premiums.append(
                    {
                        "premium_txn_id": f"PREM{idx:012d}{year_offset:02d}",
                        "policy_id": policy_id,
                        "treaty_id": treaty["treaty_id"],
                        "cedant_id": cedant["cedant_id"],
                        "accounting_date": accounting_date,
                        "gross_premium": annual_premium,
                        "ceded_premium": round(annual_premium * ceded_share, 2),
                        "currency_code": cedant["currency_code"],
                    }
                )
            if status == "ACTIVE":
                for month_offset in range(12):
                    month = _month_start(reference_date, -month_offset)
                    if month >= date(issue_date.year, issue_date.month, 1):
                        exposure.append(
                            {
                                "exposure_id": f"EXP{idx:012d}{month:%Y%m}",
                                "policy_id": policy_id,
                                "treaty_id": treaty["treaty_id"],
                                "cedant_id": cedant["cedant_id"],
                                "exposure_month": month,
                                "exposed_amount": sum_assured,
                                "exposure_fraction": 1.0,
                                "currency_code": cedant["currency_code"],
                            }
                        )
            policy_cache.append(policy)
            life_cache.append(lives[-1])
        writer.write("insured_lives", lives)
        writer.write("policies", policies)
        writer.write("coverages", coverages)
        writer.write("underwriting_cases", underwriting)
        for batch in chunks(premiums, rows_per_file):
            writer.write("premiums", batch)
        for batch in chunks(exposure, rows_per_file):
            writer.write("exposure_monthly", batch)

    claims: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    reserves: list[dict[str, Any]] = []
    life_by_id = {row["insured_id"]: row for row in life_cache}
    for idx, policy in enumerate(policy_cache, 1):
        if idx % 37:
            continue
        treaty = next(item for item in treaties if item["treaty_id"] == policy["treaty_id"])
        life_by_id[policy["insured_id"]]
        event_date = min(policy["issue_date"] + timedelta(days=365 + (idx * 17) % 1800), reference_date - timedelta(days=5))
        reported_date = min(event_date + timedelta(days=1 + idx % 30), reference_date)
        claim_status = ("PAID", "OPEN", "DENIED")[idx % 3]
        claim_amount = round(float(policy["sum_assured"]) * (1.0 if claim_status != "DENIED" else 0.2), 2)
        ceded_claim = round(claim_amount * float(treaty["ceded_share_pct"]), 2)
        claim_id = f"CLM{idx:012d}"
        claims.append(
            {
                "claim_id": claim_id,
                "policy_id": policy["policy_id"],
                "treaty_id": policy["treaty_id"],
                "insured_id": policy["insured_id"],
                "event_date": event_date,
                "reported_date": reported_date,
                "claim_status": claim_status,
                "cause_code": ("NATURAL", "CANCER", "CARDIO", "ACCIDENT")[idx % 4],
                "claim_amount": claim_amount,
                "ceded_claim_amount": ceded_claim,
                "currency_code": policy["currency_code"],
            }
        )
        if claim_status == "PAID":
            payments.append(
                {
                    "claim_payment_id": f"CPY{idx:012d}",
                    "claim_id": claim_id,
                    "payment_date": min(reported_date + timedelta(days=10 + idx % 45), reference_date),
                    "payment_amount": ceded_claim,
                    "currency_code": policy["currency_code"],
                }
            )
        elif claim_status == "OPEN":
            reserves.append(
                {
                    "reserve_id": f"RSV{idx:012d}",
                    "claim_id": claim_id,
                    "valuation_date": reference_date,
                    "case_reserve_amount": round(ceded_claim * 0.9, 2),
                    "currency_code": policy["currency_code"],
                }
            )
    for batch in chunks(claims, rows_per_file):
        writer.write("claims", batch)
    for batch in chunks(payments, rows_per_file):
        writer.write("claim_payments", batch)
    for batch in chunks(reserves, rows_per_file):
        writer.write("claim_reserves", batch)

    manifest = {
        "domain": config["domain"],
        "generation_id": generation_id,
        "preset": preset_name,
        "seed": seed,
        "reference_date": reference_date.isoformat(),
        "settings": preset,
        "counts": dict(sorted(writer.counts.items())),
        "files": writer.files,
        "relationships": {
            entity: spec.get("foreign_keys", {}) for entity, spec in config["entities"].items() if spec.get("foreign_keys")
        },
        "synthetic_only": True,
    }
    with (output / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    return manifest


def _month_start(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    manifest = build_dataset(
        config=config,
        preset_name=args.preset,
        seed=args.seed,
        reference_date=date.fromisoformat(args.reference_date),
        output=args.output,
        policy_override=args.policies,
    )
    print(json.dumps({"status": "PASS", "generation_id": manifest["generation_id"], "counts": manifest["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
