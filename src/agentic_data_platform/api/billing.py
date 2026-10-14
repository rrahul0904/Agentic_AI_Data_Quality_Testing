from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from agentic_data_platform.api.security import current_principal, production_mode
from agentic_data_platform.billing import (
    PLANS,
    EntitlementStore,
    StripeGateway,
    apply_stripe_event,
    parse_event,
    verify_stripe_signature,
)
from agentic_data_platform.errors import safe_error


router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


class CheckoutInput(BaseModel):
    plan: str = Field(default="professional", min_length=1, max_length=50)
    success_url: str = Field(min_length=1, max_length=2000)
    cancel_url: str = Field(min_length=1, max_length=2000)
    customer_email: str | None = Field(default=None, max_length=320)


class PortalInput(BaseModel):
    return_url: str = Field(min_length=1, max_length=2000)


def _store() -> EntitlementStore:
    return EntitlementStore()


def _allowed_return_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "billing return URL must be an absolute HTTP(S) URL")

    configured = {
        origin.strip().rstrip("/")
        for origin in os.getenv("ADE_BILLING_ALLOWED_RETURN_ORIGINS", "").split(",")
        if origin.strip()
    }
    if not configured and not production_mode():
        configured = {"http://127.0.0.1:3000", "http://localhost:3000"}
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if origin not in configured:
        if production_mode() and not configured:
            raise HTTPException(503, "ADE_BILLING_ALLOWED_RETURN_ORIGINS is not configured")
        raise HTTPException(400, "billing return URL origin is not allowlisted")
    return value


@router.get("/plans")
def plans() -> dict[str, object]:
    gateway = StripeGateway()
    enterprise_contact_url = os.getenv("ADE_ENTERPRISE_CONTACT_URL", "").strip() or None
    return {
        "plans": [plan.to_dict() for plan in PLANS.values()],
        "checkout_configured": gateway.configured,
        "enterprise_contact_url": enterprise_contact_url,
    }


@router.get("/entitlement")
def entitlement() -> dict[str, object]:
    principal = current_principal()
    return _store().get(principal.key_id).to_dict()


@router.post("/checkout")
def checkout(payload: CheckoutInput) -> dict[str, object]:
    principal = current_principal()
    plan = payload.plan.strip().casefold()
    configured_plan = PLANS.get(plan)
    if configured_plan is None:
        raise HTTPException(400, "unknown billing plan")
    if not configured_plan.checkout_enabled:
        raise HTTPException(400, f"{configured_plan.name} does not use automated checkout")

    gateway = StripeGateway()
    if not gateway.configured:
        raise HTTPException(503, "Stripe checkout is not configured")
    try:
        session = gateway.create_checkout(
            plan=plan,
            key_id=principal.key_id,
            success_url=_allowed_return_url(payload.success_url),
            cancel_url=_allowed_return_url(payload.cancel_url),
            customer_email=payload.customer_email,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(502, safe_error(exc)) from exc
    checkout_url = session.get("url")
    if not checkout_url:
        raise HTTPException(502, "Stripe checkout session did not return a URL")
    return {"checkout_url": str(checkout_url), "session_id": session.get("id")}


@router.post("/portal")
def portal(payload: PortalInput) -> dict[str, object]:
    principal = current_principal()
    current = _store().get(principal.key_id)
    if not current.customer_id:
        raise HTTPException(404, "no Stripe customer is associated with this principal")
    gateway = StripeGateway()
    if not gateway.secret_key:
        raise HTTPException(503, "Stripe billing portal is not configured")
    try:
        session = gateway.create_portal(
            customer_id=current.customer_id,
            return_url=_allowed_return_url(payload.return_url),
        )
    except RuntimeError as exc:
        raise HTTPException(502, safe_error(exc)) from exc
    portal_url = session.get("url")
    if not portal_url:
        raise HTTPException(502, "Stripe portal session did not return a URL")
    return {"portal_url": str(portal_url)}


@router.post("/webhook")
async def webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
) -> dict[str, object]:
    payload = await request.body()
    secret = os.getenv("ADE_STRIPE_WEBHOOK_SECRET", "").strip()
    try:
        verify_stripe_signature(payload, stripe_signature, secret)
        event = parse_event(payload)
        updated = apply_stripe_event(_store(), event)
    except ValueError as exc:
        raise HTTPException(400, safe_error(exc)) from exc
    return {
        "received": True,
        "event_id": event.get("id"),
        "entitlement_updated": updated is not None,
    }
