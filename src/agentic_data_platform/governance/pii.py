"""Deterministic enterprise PII classification with optional sample-value evidence."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class PiiFinding:
    category: str
    confidence: float
    evidence: tuple[str, ...]
    source: str


_NAME_RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "email": (re.compile(r"(^|_)(email|e_mail|mail_address)($|_)", re.I),),
    "phone": (re.compile(r"(^|_)(phone|mobile|telephone|tel_number)($|_)", re.I),),
    "ssn": (re.compile(r"(^|_)(ssn|social_security|social_security_number)($|_)", re.I),),
    "credit_card": (re.compile(r"(^|_)(credit_card|card_number|pan)($|_)", re.I),),
    "ip_address": (re.compile(r"(^|_)(ip|ip_address|client_ip|remote_addr)($|_)", re.I),),
    "person_name": (
        re.compile(r"(^|_)(first_name|last_name|full_name|given_name|surname|guest_name|customer_name)($|_)", re.I),
    ),
    "address": (
        re.compile(r"(^|_)(address|street|street_address|postal_address|mailing_address)($|_)", re.I),
    ),
    "dob": (re.compile(r"(^|_)(dob|date_of_birth|birth_date|birthday)($|_)", re.I),),
    "passport": (re.compile(r"(^|_)(passport|passport_number|passport_no)($|_)", re.I),),
    "bank_account": (
        re.compile(r"(^|_)(bank_account|account_number|routing_number|iban|swift|bic)($|_)", re.I),
    ),
    "health_identifier": (
        re.compile(r"(^|_)(mrn|medical_record|patient_id|health_id|insurance_member_id)($|_)", re.I),
    ),
    "device_identifier": (
        re.compile(r"(^|_)(device_id|advertising_id|idfa|gaid|imei|mac_address)($|_)", re.I),
    ),
    "geolocation": (
        re.compile(r"(^|_)(latitude|longitude|lat|lon|lng|geo_location|geolocation)($|_)", re.I),
    ),
    "national_identifier": (
        re.compile(r"(^|_)(national_id|tax_id|tin|aadhaar|aadhar)($|_)", re.I),
    ),
}

_DESCRIPTION_RULES: dict[str, tuple[str, ...]] = {
    "email": ("email address",),
    "phone": ("phone number", "telephone number", "mobile number"),
    "ssn": ("social security",),
    "credit_card": ("credit card", "payment card", "primary account number"),
    "ip_address": ("ip address",),
    "person_name": ("person name", "guest name", "customer name"),
    "address": ("street address", "mailing address", "home address"),
    "dob": ("date of birth", "birth date"),
    "passport": ("passport number",),
    "bank_account": ("bank account", "routing number", "iban"),
    "health_identifier": ("medical record", "patient identifier", "health identifier"),
    "device_identifier": ("device identifier", "advertising identifier", "imei"),
    "geolocation": ("latitude", "longitude", "geolocation"),
    "national_identifier": ("national identifier", "tax identifier", "aadhaar"),
}

_VALUE_RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "email": (re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I),),
    "phone": (re.compile(r"^\+?[0-9][0-9(). -]{7,18}[0-9]$"),),
    "ssn": (re.compile(r"^\d{3}-?\d{2}-?\d{4}$"),),
    "credit_card": (re.compile(r"^(?:\d[ -]*?){13,19}$"),),
    "passport": (re.compile(r"^[A-Z0-9]{6,12}$", re.I),),
    "bank_account": (
        re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$", re.I),
        re.compile(r"^\d{8,17}$"),
    ),
    "device_identifier": (
        re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$", re.I),
        re.compile(r"^[0-9A-F]{15}$", re.I),
        re.compile(r"^[0-9A-F-]{32,36}$", re.I),
    ),
    "geolocation": (re.compile(r"^-?\d{1,3}(?:\.\d+)?\s*,\s*-?\d{1,3}(?:\.\d+)?$"),),
}


def _luhn(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        value_digit = digit
        if index % 2 == parity:
            value_digit *= 2
            if value_digit > 9:
                value_digit -= 9
        checksum += value_digit
    return checksum % 10 == 0


def _value_categories(value: Any) -> set[str]:
    text = str(value).strip()
    if not text:
        return set()
    result = set()
    for category, patterns in _VALUE_RULES.items():
        if any(pattern.fullmatch(text) for pattern in patterns):
            if category == "credit_card" and not _luhn(text):
                continue
            result.add(category)
    try:
        ipaddress.ip_address(text)
        result.add("ip_address")
    except ValueError:
        pass
    return result


def classify_column(
    name: str,
    *,
    data_type: str | None = None,
    description: str | None = None,
    tags: Sequence[Any] = (),
    sample_values: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    lower_description = (description or "").casefold()
    tag_text = " ".join(str(item) for item in tags).casefold()

    for category, patterns in _NAME_RULES.items():
        if any(pattern.search(name) for pattern in patterns):
            scores[category] = max(scores.get(category, 0), 0.82)
            evidence.setdefault(category, []).append(f"column name: {name}")
    for category, phrases in _DESCRIPTION_RULES.items():
        if any(phrase in lower_description for phrase in phrases):
            scores[category] = max(scores.get(category, 0), 0.88)
            evidence.setdefault(category, []).append("column description")
        if any(phrase in tag_text for phrase in phrases):
            scores[category] = max(scores.get(category, 0), 0.95)
            evidence.setdefault(category, []).append("metadata tag")

    if sample_values is not None:
        category_hits: dict[str, int] = {}
        non_null = [value for value in sample_values if value is not None and str(value).strip()]
        for value in non_null:
            for category in _value_categories(value):
                category_hits[category] = category_hits.get(category, 0) + 1
        for category, hits in category_hits.items():
            ratio = hits / max(1, len(non_null))
            if hits >= 2 or ratio >= 0.5:
                sample_confidence = min(0.99, 0.75 + ratio * 0.24)
                scores[category] = max(scores.get(category, 0), sample_confidence)
                evidence.setdefault(category, []).append(
                    f"sample pattern: {hits}/{len(non_null)} values"
                )

    findings = [
        PiiFinding(
            category=category,
            confidence=round(score, 3),
            evidence=tuple(evidence.get(category, ())),
            source="metadata+sample" if sample_values is not None else "metadata",
        )
        for category, score in scores.items()
    ]
    return [asdict(item) for item in sorted(findings, key=lambda item: (-item.confidence, item.category))]


def scan_metadata(
    columns: Iterable[Mapping[str, Any]],
    *,
    samples: Mapping[str, Sequence[Any]] | None = None,
) -> dict[str, Any]:
    findings = []
    for column in columns:
        object_id = str(column.get("object_id") or "")
        name = str(column.get("column_name") or column.get("name") or "")
        sample_key = f"{object_id}.{name}" if object_id else name
        classified = classify_column(
            name,
            data_type=str(column.get("data_type") or ""),
            description=column.get("comment") or column.get("description"),
            tags=column.get("tags") or (),
            sample_values=(samples or {}).get(sample_key) if samples is not None else None,
        )
        for item in classified:
            findings.append({
                "object_id": object_id or None,
                "column": name,
                **item,
            })
    return {
        "status": "PASS",
        "classification_count": len(findings),
        "findings": findings,
        "sample_scanning": samples is not None,
    }


def scan_query(sql: str, schema_context: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    lower = sql.casefold()
    findings = []
    for table, columns in schema_context.items():
        if table.casefold() not in lower and table.split(".")[-1].casefold() not in lower:
            continue
        for name, metadata in columns.items():
            details = metadata if isinstance(metadata, Mapping) else {"data_type": metadata}
            classified = classify_column(
                str(name),
                data_type=str(details.get("data_type") or details.get("type") or ""),
                description=details.get("description"),
                tags=details.get("tags") or (),
            )
            if classified and (str(name).casefold() in lower or "*" in sql):
                findings.append({"table": table, "column": name, "classifications": classified})
    return {
        "status": "WARN" if findings else "PASS",
        "pii_columns_referenced": findings,
        "count": len(findings),
    }
