# Commercial deployment readiness

This is the final environment gate between a certified ADE release and a hosted environment that can be offered to customers.

Repository CI proves the software release. It does not prove that an operator supplied safe credentials, durable production services, TLS, a live Stripe account, or a real customer warehouse. Run this gate in the target environment before calling that environment production-ready.

## 1. Start from the production template

Copy `deploy/production.env.example` into the target platform's secret/configuration system. Do not commit the populated values.

For a self-hosted Community/Professional installation, `ADE_BILLING_ENFORCEMENT=optional` is appropriate. For a paid hosted SaaS environment, use `ADE_BILLING_ENFORCEMENT=required` only after Stripe Checkout and signed webhook delivery have been verified.

## 2. Run the fail-closed environment doctor

Load the target environment and run:

```bash
python scripts/production_readiness.py --output artifacts/production-readiness.json
```

Exit code `0` means no blocking configuration failures were found. Exit code `2` means at least one production blocker exists.

The doctor currently validates:

- an exact 40-character release SHA;
- non-placeholder API credentials;
- non-placeholder web credentials;
- the server-side web service token maps to a configured API principal;
- managed Git customer sources use HTTPS and an explicit ref;
- paid SaaS enforcement has Stripe secret, recurring Price, webhook secret, and HTTPS return origins;
- persistence topology is surfaced as a warning when it is still single-node/local.

Warnings do not change the exit code because Community/self-hosted installations can legitimately use local persistence or optional billing. Operators must still review warnings against the intended deployment model.

## 3. Verify the deployed exact release

The automatic `production-release` workflow on substantive `main` changes certifies the exact SHA and, only after certification succeeds, publishes immutable API and web images to GHCR with provenance attestations and a `production-release.json` manifest.

Deploy image digests from that manifest rather than a mutable `latest` tag. Set `ADE_COMMIT_SHA` to the same release SHA used by both images.

## 4. Paid hosted launch gate

Before accepting real customer payments, retain evidence that all of the following happened in the actual hosted environment:

- HTTPS/TLS and the public hostname are working;
- authentication rejects unauthenticated product access;
- the deployed image digests match the release manifest;
- a Stripe Checkout Session completes successfully;
- the signed Stripe webhook reaches ADE and activates the expected `key_id`;
- the customer can create a Billing Portal session;
- cancellation or subscription deletion removes the paid entitlement;
- restart/redeploy preserves entitlement state;
- backup and restore of control-plane/billing state has been exercised;
- target Snowflake/dbt/Airflow integrations use least-privilege credentials and their required live certification is captured;
- tax, invoice, refund, privacy/terms, support ownership, and customer-facing pricing decisions are complete for the business operating the service.

Until those external checks are captured, the repository can be described as commercially packaged and deployable, but the specific hosted environment must not be described as accepting production payments or fully customer-certified.
