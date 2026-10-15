from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx


_RECONCILED_EVENT_TYPES = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
}


def subscription_id_for_event(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    if event_type not in _RECONCILED_EVENT_TYPES:
        return None
    obj = event.get("data", {}).get("object", {})
    if not isinstance(obj, dict):
        return None
    value = obj.get("subscription") if event_type == "checkout.session.completed" else obj.get("id")
    subscription_id = str(value or "").strip()
    return subscription_id or None


def reconcile_with_current_subscription(
    event: dict[str, Any],
    *,
    secret_key: str | None = None,
) -> dict[str, Any]:
    """Resolve entitlement-affecting webhooks against Stripe's current subscription state.

    Stripe retries and delivery order must never allow an older webhook payload to be
    treated as the current billing truth. For Checkout completion and subscription
    create/update events, retrieve the current subscription object before applying the
    local entitlement transition. Deletion events remain authoritative as delivered.
    """

    subscription_id = subscription_id_for_event(event)
    if subscription_id is None:
        return event

    key = (secret_key or os.getenv("ADE_STRIPE_SECRET_KEY", "")).strip()
    if not key:
        raise RuntimeError("ADE_STRIPE_SECRET_KEY is required for webhook reconciliation")

    response = httpx.get(
        f"https://api.stripe.com/v1/subscriptions/{quote(subscription_id, safe='')}",
        headers={"Authorization": f"Bearer {key}"},
        timeout=20.0,
    )
    if response.is_error:
        detail = "Stripe subscription reconciliation failed"
        try:
            detail = str(response.json().get("error", {}).get("message") or detail)
        except (ValueError, AttributeError):
            pass
        raise RuntimeError(detail)

    subscription = response.json()
    if not isinstance(subscription, dict) or not subscription.get("id"):
        raise RuntimeError("Stripe returned an invalid subscription during reconciliation")

    return {
        "id": event.get("id"),
        "created": event.get("created"),
        "type": "customer.subscription.updated",
        "data": {"object": subscription},
    }
