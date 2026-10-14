"use client";

import { useEffect, useState } from "react";

type Plan = {
  id: string;
  name: string;
  price_label: string;
  audience: string;
  features: string[];
  checkout_enabled: boolean;
};

type PlanResponse = {
  plans: Plan[];
  checkout_configured: boolean;
};

export default function PricingPage() {
  const [data, setData] = useState<PlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/ade/api/v1/billing/plans", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Pricing is unavailable");
        return response.json() as Promise<PlanResponse>;
      })
      .then(setData)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Pricing is unavailable");
      });
  }, []);

  async function checkout(plan: Plan) {
    setBusy(plan.id);
    setError(null);
    try {
      const origin = window.location.origin;
      const response = await fetch("/api/ade/api/v1/billing/checkout", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          plan: plan.id,
          success_url: `${origin}/pricing?checkout=success`,
          cancel_url: `${origin}/pricing?checkout=cancelled`,
        }),
      });
      const payload = await response.json() as { checkout_url?: string; detail?: string };
      if (!response.ok || !payload.checkout_url) {
        throw new Error(payload.detail || "Checkout could not be started");
      }
      window.location.assign(payload.checkout_url);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Checkout could not be started");
      setBusy(null);
    }
  }

  const plans = data?.plans || [];

  return (
    <main style={{ maxWidth: 1180, margin: "0 auto", padding: "64px 24px" }}>
      <p style={{ letterSpacing: 2, textTransform: "uppercase", fontWeight: 700 }}>
        Agentic Data Engineering OS
      </p>
      <h1 style={{ fontSize: 48, marginBottom: 12 }}>Choose how you run ADE</h1>
      <p style={{ fontSize: 19, maxWidth: 760, opacity: 0.78, lineHeight: 1.6 }}>
        Start locally for free, move a production team to Professional, or use Enterprise
        for private deployment, certification, and commercial support.
      </p>

      {error ? (
        <div role="alert" style={{ marginTop: 24, padding: 16, border: "1px solid currentColor" }}>
          {error}
        </div>
      ) : null}

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 20,
          marginTop: 42,
        }}
      >
        {plans.map((plan) => (
          <article
            key={plan.id}
            style={{ border: "1px solid rgba(127,127,127,.35)", borderRadius: 18, padding: 28 }}
          >
            <h2 style={{ fontSize: 28, marginBottom: 8 }}>{plan.name}</h2>
            <div style={{ fontSize: 32, fontWeight: 800, marginBottom: 14 }}>{plan.price_label}</div>
            <p style={{ minHeight: 58, opacity: 0.75 }}>{plan.audience}</p>
            <ul style={{ paddingLeft: 20, lineHeight: 1.8, minHeight: 160 }}>
              {plan.features.map((feature) => <li key={feature}>{feature}</li>)}
            </ul>
            {plan.id === "community" ? (
              <a href="/" style={{ fontWeight: 700 }}>Use Community</a>
            ) : plan.checkout_enabled ? (
              <button
                type="button"
                disabled={!data?.checkout_configured || busy === plan.id}
                onClick={() => checkout(plan)}
                style={{ padding: "12px 18px", borderRadius: 10, fontWeight: 700, cursor: "pointer" }}
              >
                {busy === plan.id
                  ? "Opening checkout…"
                  : data?.checkout_configured
                    ? "Start Professional"
                    : "Checkout not configured"}
              </button>
            ) : (
              <a href="mailto:sales@example.com" style={{ fontWeight: 700 }}>
                Contact sales
              </a>
            )}
          </article>
        ))}
      </section>

      <p style={{ marginTop: 32, opacity: 0.65 }}>
        Enterprise sales contact is deployment-specific. Replace the placeholder sales address
        before a public commercial launch.
      </p>
    </main>
  );
}
