# ADE monetization runbook

ADE supports a local-first Community edition plus Professional subscription checkout and an Enterprise sales path. Billing is deliberately fail-closed: no payment can be initiated until a real Stripe account, recurring Price, webhook signing secret, and allowed return origin are configured.

## Packaging

| Plan | Default positioning | Checkout |
| --- | --- | --- |
| Community | Local evaluation and individual engineers | Free; no checkout |
| Professional | Production data engineering teams | Stripe subscription |
| Enterprise | Private deployment, certification, and commercial support | Sales-assisted |

The Professional display price defaults to `$99/month` and can be overridden with `ADE_PROFESSIONAL_PRICE_LABEL`. The actual amount charged is always controlled by the Stripe Price referenced by `ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY`; ADE never derives a charge amount from the display label.

## Required configuration for paid checkout

Set these only in the API runtime or its secret manager. Never expose them to the Next.js client bundle.

```text
ADE_STRIPE_SECRET_KEY=sk_...
ADE_STRIPE_WEBHOOK_SECRET=whsec_...
ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY=price_...
ADE_BILLING_ALLOWED_RETURN_ORIGINS=https://your-ade.example.com
ADE_ENTERPRISE_CONTACT_URL=https://your-company.example.com/contact-sales
```

`ADE_BILLING_DATABASE` defaults to `.ade/billing.db`. The production Compose runtime pins it to `/state/billing.db`, which is on the existing durable state volume.

## Stripe setup

1. Create a recurring monthly Professional product/price in Stripe.
2. Put the resulting Price ID in `ADE_STRIPE_PRICE_PROFESSIONAL_MONTHLY`.
3. Create a webhook endpoint pointing to `https://<api-host>/api/v1/billing/webhook`.
4. Subscribe the webhook endpoint to:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Put the webhook signing secret in `ADE_STRIPE_WEBHOOK_SECRET`.
6. Set `ADE_BILLING_ALLOWED_RETURN_ORIGINS` to the exact HTTPS origin of the ADE web application.
7. Restart the API and verify `GET /api/v1/billing/plans` reports `checkout_configured: true` through an authenticated request.

The Stripe webhook is the only billing route exempt from ADE bearer authentication. It is accepted only after Stripe HMAC signature validation and timestamp tolerance checks.

## Customer flow

1. An authenticated ADE principal opens `/pricing`.
2. The web proxy forwards the principal's ADE API credential to the billing API.
3. Professional checkout creates a Stripe Checkout Session and stamps both the Checkout Session and resulting subscription with `ade_key_id` and `ade_plan` metadata.
4. Stripe sends the signed webhook to ADE.
5. ADE persists the subscription state against the authenticated `key_id`.
6. `GET /api/v1/billing/entitlement` returns the current local entitlement.
7. An entitled customer can request a Stripe Billing Portal session through `POST /api/v1/billing/portal`.

## Release gates before accepting real money

Do not enable live-mode checkout until all of these are true:

- GitHub CI is green on the exact release commit.
- The production ADE API and web health checks pass after restart.
- TLS is enabled for the public origin.
- Production bearer credentials and web authentication are configured.
- The Stripe webhook is receiving and validating signed live-mode events.
- A real test purchase activates the expected ADE `key_id`, cancellation downgrades it, and restart preserves the billing record.
- Refund, failed-payment, tax, invoice, terms/privacy, support, and operational ownership decisions have been made for the chosen sales jurisdiction and business model.

The repository code supplies the checkout, webhook, persistence, entitlement, portal, and pricing surfaces. Stripe account creation, legal/business configuration, tax settings, live Price creation, domain/DNS/TLS, and production credentials are external deployment gates and must not be represented as complete until actually verified.
