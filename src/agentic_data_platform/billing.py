from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

import httpx


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_label: str
    audience: str
    features: tuple[str, ...]
    checkout_enabled: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["features"] = list(self.features)
        return payload


PLANS: dict[str, Plan] = {
    "community": Plan(
        id="community",
        name="Community",
        price_label="$0",
        audience="Individual engineers and local evaluation",
        features=(
            "Local-first ADE runtime",
            "Core investigation and data-quality workflows",
            "Community support",
        ),
        checkout_enabled=False,
    ),
    "professional": Plan(
        id="professional",
        name="Professional",
        price_label=os.getenv("ADE_PROFESSIONAL_PRICE_LABEL", "$99/month"),
        audience="Production data engineering teams",
        features=(
            "Everything in Community",
            "Production authentication and durable state",
            "Governed approvals and audit evidence",
            "Priority support",
        ),
        checkout_enabled=True,
    ),
    "enterprise": Plan(
        id="enterprise",
        name="Enterprise",
        price_label="Custom",
        audience="Organizations requiring private deployment and enterprise controls",
        features=(
            "Everything in Professional",
            "Private deployment and enterprise onboarding",
            "Security and target-account certification support",
            "Commercial support agreement",
        ),
        checkout_enabled=False,
    ),
}


@dataclass(frozen=True)
class Entitlement:
    key_id: str
    plan: str
    status: str
    customer_id: str | None = None
    subscription_id: str | None = None
    current_period_end: str | None = None
    updated_at: str | None = None

    @property
    def active(self) -> bool:
        return self.status in {"active", "trialing"} or self.plan == "community"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "active": self.active}


class EntitlementStore:
    def __init__(self, database: str | Path | None = None) -> None:
        configured = database or os.getenv("ADE_BILLING_DATABASE", ".ade/billing.db")
        self.database = Path(configured).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_entitlements (
                    key_id TEXT PRIMARY KEY,
                    plan TEXT NOT NULL,
                    status TEXT NOT NULL,
                    customer_id TEXT,
                    subscription_id TEXT,
                    current_period_end TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, key_id: str) -> Entitlement:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM billing_entitlements WHERE key_id = ?",
                (key_id,),
            ).fetchone()
        if row is None:
            return Entitlement(key_id=key_id, plan="community", status="active")
        return Entitlement(
            key_id=str(row["key_id"]),
            plan=str(row["plan"]),
            status=str(row["status"]),
            customer_id=row["customer_id"],
            subscription_id=row["subscription_id"],
            current_period_end=row["current_period_end"],
            updated_at=row["updated_at"],
        )

    def upsert(self, entitlement: Entitlement) -> Entitlement:
        if entitlement.plan not in PLANS:
            raise ValueError(f"unknown plan: {entitlement.plan}")
        updated_at = entitlement.updated_at or datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO billing_entitlements (
                    key_id, plan, status, customer_id, subscription_id,
                    current_period_end, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                    plan = excluded.plan,
                    status = excluded.status,
                    customer_id = excluded.customer_id,
                    subscription_id = excluded.subscription_id,
                    current_period_end = excluded.current_period_end,
                    updated_at = excluded.updated_at
                """,
                (
                    entitlement.key_id,
                    entitlement.plan,
                    entitlement.status,
                    entitlement.customer_id,
                    entitlement.subscription_id,
                    entitlement.current_period_end,
                    updated_at,
                ),
            )
        return self.get(entitlement.key_id)


class StripeGateway:
    base_url = "https://api.stripe.com/v1"

    def __init__(self, secret_key: str | None = None) -> None:
        self.secret_key = (secret_key or os.getenv("ADE_STRIPE_SECRET_KEY", "")).strip()

    @property
    def configured(self) -> bool:
        return bool(self.secret_key and os.getenv("ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY", "").strip())

    def _post(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        if not self.secret_key:
            raise RuntimeError("ADE_STRIPE_SECRET_KEY is not configured")
        response = httpx.post(
            f"{self.base_url}/{path.lstrip('/')}",
            data=data,
            headers={"Authorization": f"Bearer {self.secret_key}"},
            timeout=20.0,
        )
        if response.is_error:
            detail = "Stripe request failed"
            try:
                detail = str(response.json().get("error", {}).get("message") or detail)
            except (ValueError, AttributeError):
                pass
            raise RuntimeError(detail)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Stripe returned an invalid response")
        return payload

    def create_checkout(
        self,
        *,
        plan: str,
        key_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
    ) -> dict[str, Any]:
        if plan != "professional":
            raise ValueError("automated checkout is currently available for the professional plan only")
        price_id = os.getenv("ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY", "").strip()
        if not price_id:
            raise RuntimeError("ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY is not configured")
        data = {
            "mode": "subscription",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": key_id,
            "metadata[ade_key_id]": key_id,
            "metadata[ade_plan]": plan,
            "subscription_data[metadata][ade_key_id]": key_id,
            "subscription_data[metadata][ade_plan]": plan,
        }
        if customer_email:
            data["customer_email"] = customer_email
        return self._post("checkout/sessions", data)

    def create_portal(self, *, customer_id: str, return_url: str) -> dict[str, Any]:
        return self._post(
            "billing_portal/sessions",
            {"customer": customer_id, "return_url": return_url},
        )


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    *,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> None:
    if not secret:
        raise ValueError("Stripe webhook secret is not configured")
    values: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        key, separator, value = item.partition("=")
        if separator:
            values.setdefault(key.strip(), []).append(value.strip())
    timestamp_values = values.get("t", [])
    signatures = values.get("v1", [])
    if not timestamp_values or not signatures:
        raise ValueError("invalid Stripe signature header")
    try:
        timestamp = int(timestamp_values[0])
    except ValueError as exc:
        raise ValueError("invalid Stripe signature timestamp") from exc
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        raise ValueError("Stripe webhook signature is outside the allowed tolerance")
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise ValueError("Stripe webhook signature mismatch")


def _period_end(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def apply_stripe_event(store: EntitlementStore, event: dict[str, Any]) -> Entitlement | None:
    event_type = str(event.get("type") or "")
    obj = event.get("data", {}).get("object", {})
    if not isinstance(obj, dict):
        return None
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    key_id = str(metadata.get("ade_key_id") or obj.get("client_reference_id") or "").strip()
    if not key_id:
        return None

    plan = str(metadata.get("ade_plan") or "professional").strip().casefold()
    if plan not in PLANS:
        plan = "professional"

    if event_type == "checkout.session.completed":
        entitlement = Entitlement(
            key_id=key_id,
            plan=plan,
            status="active",
            customer_id=str(obj.get("customer") or "") or None,
            subscription_id=str(obj.get("subscription") or "") or None,
        )
        return store.upsert(entitlement)

    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        status = str(obj.get("status") or "inactive").casefold()
        entitlement = Entitlement(
            key_id=key_id,
            plan=plan,
            status=status,
            customer_id=str(obj.get("customer") or "") or None,
            subscription_id=str(obj.get("id") or "") or None,
            current_period_end=_period_end(obj.get("current_period_end")),
        )
        return store.upsert(entitlement)

    if event_type == "customer.subscription.deleted":
        previous = store.get(key_id)
        return store.upsert(
            Entitlement(
                key_id=key_id,
                plan="community",
                status="canceled",
                customer_id=str(obj.get("customer") or previous.customer_id or "") or None,
                subscription_id=str(obj.get("id") or previous.subscription_id or "") or None,
            )
        )
    return None


def parse_event(payload: bytes) -> dict[str, Any]:
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Stripe webhook payload must be valid JSON") from exc
    if not isinstance(event, dict):
        raise ValueError("Stripe webhook payload must be a JSON object")
    return event
