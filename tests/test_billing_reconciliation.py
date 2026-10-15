from __future__ import annotations

from typing import Any

import pytest

from agentic_data_platform.billing_reconciliation import (
    reconcile_with_current_subscription,
    subscription_id_for_event,
)


class _Response:
    def __init__(self, payload: dict[str, Any], *, is_error: bool = False) -> None:
        self._payload = payload
        self.is_error = is_error

    def json(self) -> dict[str, Any]:
        return self._payload


def _checkout_event() -> dict[str, Any]:
    return {
        "id": "evt_checkout",
        "created": 100,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "subscription": "sub_123",
                "client_reference_id": "key-a",
            }
        },
    }


def test_subscription_id_for_checkout_and_subscription_events() -> None:
    assert subscription_id_for_event(_checkout_event()) == "sub_123"
    assert subscription_id_for_event(
        {"type": "customer.subscription.updated", "data": {"object": {"id": "sub_456"}}}
    ) == "sub_456"
    assert subscription_id_for_event(
        {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_789"}}}
    ) is None


def test_reconciliation_uses_current_subscription_state(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> _Response:
        captured.update(url=url, headers=headers, timeout=timeout)
        return _Response(
            {
                "id": "sub_123",
                "customer": "cus_123",
                "status": "past_due",
                "metadata": {"ade_key_id": "key-a", "ade_plan": "professional"},
            }
        )

    monkeypatch.setattr("agentic_data_platform.billing_reconciliation.httpx.get", fake_get)
    reconciled = reconcile_with_current_subscription(_checkout_event(), secret_key="sk_test_123")

    assert reconciled["type"] == "customer.subscription.updated"
    assert reconciled["data"]["object"]["status"] == "past_due"
    assert captured["url"].endswith("/subscriptions/sub_123")
    assert captured["headers"] == {"Authorization": "Bearer sk_test_123"}


def test_deleted_subscription_event_is_not_reconciled(monkeypatch) -> None:
    event = {
        "id": "evt_deleted",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_123"}},
    }

    def unexpected_get(*args: Any, **kwargs: Any) -> _Response:
        raise AssertionError("deleted event must not query Stripe")

    monkeypatch.setattr("agentic_data_platform.billing_reconciliation.httpx.get", unexpected_get)
    assert reconcile_with_current_subscription(event, secret_key="sk_test_123") is event


def test_reconciliation_fails_closed_without_secret() -> None:
    with pytest.raises(RuntimeError, match="ADE_STRIPE_SECRET_KEY"):
        reconcile_with_current_subscription(_checkout_event(), secret_key="")


def test_reconciliation_fails_closed_on_stripe_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "agentic_data_platform.billing_reconciliation.httpx.get",
        lambda *args, **kwargs: _Response({"error": {"message": "temporary outage"}}, is_error=True),
    )
    with pytest.raises(RuntimeError, match="temporary outage"):
        reconcile_with_current_subscription(_checkout_event(), secret_key="sk_test_123")
