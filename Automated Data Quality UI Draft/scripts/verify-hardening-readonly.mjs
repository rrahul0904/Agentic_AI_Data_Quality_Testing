#!/usr/bin/env node

// Read-only cross-page contract smoke check. Every request in this script is GET.
// It never submits a plan, approves a rule, runs a job, or verifies an LLM.

const uiOrigin = (process.env.ADE_UI_ORIGIN || "http://127.0.0.1:3020").replace(/\/$/, "");
const apiOrigin = (process.env.ADE_API_ORIGIN || "http://127.0.0.1:8011").replace(/\/$/, "");
const projectId = process.env.ADE_AUDIT_PROJECT_ID || "data-quality-testing-beta";
const environment = process.env.ADE_AUDIT_ENVIRONMENT || "development";
const query = new URLSearchParams({ project_id: projectId, environment }).toString();
const failures = [];

async function get(label, url) {
  try {
    const response = await fetch(url, { method: "GET", cache: "no-store", signal: AbortSignal.timeout(8000) });
    const body = await response.text();
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    try { return { response, value: JSON.parse(body) }; }
    catch { return { response, value: body }; }
  } catch (error) {
    failures.push(`${label}: ${error instanceof Error ? error.message : "request failed"}`);
    return null;
  }
}

const [ui, health, ready, onboarding, quality, overview, readiness, agentStatus] = await Promise.all([
  get("UI root", `${uiOrigin}/`),
  get("API health", `${apiOrigin}/healthz`),
  get("API readiness", `${apiOrigin}/readyz`),
  get("Project onboarding", `${uiOrigin}/api/onboarding?${query}`),
  get("Quality Rules", `${uiOrigin}/api/quality-plans?${query}`),
  get("Overview", `${uiOrigin}/api/operations?${query}`),
  get("Provider configuration status", `${uiOrigin}/api/demo/readiness?${query}`),
  get("Ask AI project configuration", `${uiOrigin}/api/agent?${query}`),
]);

function check(condition, message) {
  if (!condition) failures.push(message);
}

check(ui?.response.status === 200, "UI root did not return HTTP 200");
check(health?.value?.status === "ok" || health?.value?.status === "healthy", "API /healthz did not report a healthy process");
check(ready?.value?.status === "ready", "API /readyz did not report ready (HTTP alone is insufficient)");

const selected = onboarding?.value?.selectedSourceTables;
const activeScope = onboarding?.value?.sourceTableScopeId;
check(Array.isArray(selected), "Onboarding did not return selectedSourceTables");
check(Boolean(activeScope), "Onboarding has no active source-table scope");

const plan = quality?.value?.plan;
const overviewPlan = overview?.value?.plan;
if (plan?.plan_id) {
  check(plan.source_table_scope_id === activeScope, "Quality plan scope differs from onboarding active source-table scope");
  check(overviewPlan?.plan_id === plan.plan_id, "Overview plan ID differs from the Rules page plan ID");
  check(overviewPlan?.status === plan.status, "Overview plan status differs from the Rules page status");
  check(Array.isArray(overviewPlan?.checks) && overviewPlan.checks.length === (plan.checks?.length ?? 0), "Overview plan check count differs from the Rules page");
} else {
  check(!overviewPlan?.plan_id, "Overview claims a plan exists while the scoped Rules API returned no plan");
}

const providerConfig = readiness?.value?.configuration?.model_provider;
const configuredAgent = agentStatus?.value;
check(Boolean(providerConfig?.provider && providerConfig?.model), "Readiness omitted provider/model configuration metadata");
check(providerConfig?.provider === configuredAgent?.provider, "Readiness provider does not match Ask AI project configuration");
check(providerConfig?.model === configuredAgent?.model, "Readiness model does not match Ask AI project configuration");
check(providerConfig?.credential_present === configuredAgent?.credential_present, "Readiness key-presence state does not match Ask AI project configuration");
check(readiness?.value?.readiness_request?.model_verified === false, "This read-only smoke unexpectedly performed a model verification");

const summary = {
  project: projectId,
  environment,
  ui_http: ui?.response.status ?? null,
  api_health: health?.value?.status ?? "unavailable",
  api_readiness: ready?.value?.status ?? "unavailable",
  selected_source_tables: Array.isArray(selected) ? selected.length : null,
  active_source_scope: activeScope ?? null,
  rules_plan: plan?.plan_id ? { id: plan.plan_id, status: plan.status, checks: plan.checks?.length ?? 0 } : null,
  overview_plan_id: overviewPlan?.plan_id ?? null,
  model_configuration: providerConfig ? { provider: providerConfig.provider, model: providerConfig.model, credential_present: providerConfig.credential_present } : null,
  ask_ai_configuration: configuredAgent ? { provider: configuredAgent.provider, model: configuredAgent.model, credential_present: configuredAgent.credential_present } : null,
  mode: "read-only; no provider verification or workflow execution",
};

console.log(JSON.stringify(summary, null, 2));
if (failures.length) {
  console.error("\nCross-page checks failed:\n- " + failures.join("\n- "));
  process.exitCode = 1;
} else {
  console.log("\nRead-only cross-page checks passed.");
}
