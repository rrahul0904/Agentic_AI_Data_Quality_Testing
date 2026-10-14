from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from agentic_data_platform.billing import (
    EntitlementStore,
    apply_stripe_event,
    parse_event,
    verify_stripe_signature,
)


def _signature(payload: bytes, secret: str, timestamp: int) -> str:
    digest = hmac.new(
        secret.encode(),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_stripe_signature_accepts_valid_payload() -> None:
    payload = b'{"id":"evt_1"}'
    secret = "whsec_test"
    verify_stripe_signature(
        payload,
        _signature(payload, secret, 1000),
        secret,
        now=1000,
    )


def test_stripe_signature_rejects_tampering() -> None:
    payload = b'{"id":"evt_1"}'
    secret = "whsec_test"
    signature = _signature(payload, secret, 1000)
    with pytest.raises(ValueError, match="mismatch"):
        verify_stripe_signature(b'{"id":"evt_changed"}', signature, secret, now=1000)


def test_stripe_signature_rejects_stale_event() -> None:
    payload = b'{}'
    secret = "whsec_test"
    with pytest.raises(ValueError, match="tolerance"):
        verify_stripe_signature(payload, _signature(payload, secret, 1000), secret, now=1400)


def test_entitlement_defaults_to_community(tmp_path) -> None:
    store = EntitlementStore(tmp_path / "billing.db")
    entitlement = store.get("key-a")
    assert entitlement.plan == "community"
    assert entitlement.active is True


def test_checkout_event_activates_professional_entitlement(tmp_path) -> None:
    store = EntitlementStore(tmp_path / "billing.db")
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "key-a",
                "customer": "cus_123",
                "subscription": "sub_123",
                "metadata": {"ade_key_id": "key-a", "ade_plan": "professional"},
            }
        },
    }
    result = apply_stripe_event(store, event)
    assert result is not None
    assert result.plan == "professional"
    assert result.status == "active"
    assert result.customer_id == "cus_123"


def test_subscription_delete_falls_back_to_community(tmp_path) -> None:
    store = EntitlementStore(tmp_path / "billing.db")
    apply_stripe_event(
        store,
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "key-a",
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    "metadata": {"ade_key_id": "key-a", "ade_plan": "professional"},
                }
            },
        },
    )
    result = apply_stripe_event(
        store,
        {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_123",
                    "metadata": {"ade_key_id": "key-a", "ade_plan": "professional"},
                }
            },
        },
    )
    assert result is not None
    assert result.plan == "community"
    assert result.status == "canceled"
    assert result.active is False


def test_parse_event_requires_json_object() -> None:
    with pytest.raises(ValueError):
        parse_event(json.dumps(["not", "an", "object"]).encode())
