import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const base = (process.env.ADQ_UI_URL || "http://127.0.0.1:3020").replace(/\/$/, "");
const projectId = process.env.ADQ_PROJECT_ID || "data-quality-testing-beta";
const environment = process.env.ADQ_ENVIRONMENT || "development";
const outputDir = join(process.cwd(), "artifacts", "phase3");

function scoped(path, extra = {}) {
  const url = new URL(path, base);
  url.searchParams.set("project_id", projectId);
  url.searchParams.set("environment", environment);
  for (const [key, value] of Object.entries(extra)) url.searchParams.set(key, value);
  return url;
}

async function getJson(url) {
  const response = await fetch(url);
  const text = await response.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`${url} returned non-JSON ${response.status}: ${text.slice(0, 200)}`);
  }
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body;
}

const checks = [];
const failures = [];
function check(name, passed, details) {
  const result = { name, passed, details };
  checks.push(result);
  if (!passed) failures.push(result);
}

try {
  const monitoringUrl = scoped("/api/monitoring");
  const monitoring = await getJson(monitoringUrl);
  check(
    "Monitoring returns runs without a table filter",
    Array.isArray(monitoring.items) && monitoring.status !== "NO_ACTIVE_SCOPE",
    { status: monitoring.status || null, count: monitoring.count, total: monitoring.total },
  );
  check(
    "Monitoring response is locked to requested project/environment",
    monitoring.workspace?.projectId === projectId && monitoring.workspace?.environment === environment &&
      monitoring.workspace?.requestedProjectId === projectId && monitoring.workspace?.requestedEnvironment === environment,
    { workspace: monitoring.workspace },
  );

  const run = monitoring.items?.find((item) => item?.run_id);
  if (run) {
    const detailUrl = scoped(`/api/monitoring/runs/${encodeURIComponent(run.run_id)}`);
    const detail = await getJson(detailUrl);
    check("Returned run opens its exact detail", detail.run_id === run.run_id, { requested: run.run_id, returned: detail.run_id });
    check(
      "Run detail preserves project/environment scope",
      detail.plan?.project_id === projectId && detail.plan?.environment === environment,
      { plan: { project_id: detail.plan?.project_id, environment: detail.plan?.environment } },
    );
  } else {
    check("Returned run opens its exact detail", false, { reason: "No run was available in the scoped monitoring response" });
  }

  const filtered = await getJson(scoped("/api/monitoring", { asset: "definitely-not-a-real-table" }));
  check(
    "Unknown table filter does not broaden scope",
    filtered.status === "NO_MATCHING_ASSET_FILTER" && Array.isArray(filtered.items) && filtered.items.length === 0,
    { status: filtered.status, count: filtered.count, total: filtered.total },
  );

  const actions = await getJson(scoped("/api/actions"));
  check(
    "Direct actions route returns workspace scope",
    actions.workspace?.projectId === projectId && actions.workspace?.environment === environment,
    { workspace: actions.workspace },
  );

  const report = {
    base,
    projectId,
    environment,
    checks,
    failures,
    passed: failures.length === 0,
    note: "Read-only API/frontend contract verification; no plan, approval, execution, or provider mutation was submitted.",
  };
  await mkdir(outputDir, { recursive: true });
  await writeFile(join(outputDir, "api-contract-report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
} catch (error) {
  const report = {
    base,
    projectId,
    environment,
    checks,
    failures: [...failures, { name: "contract runner", passed: false, details: error instanceof Error ? error.message : String(error) }],
    passed: false,
  };
  await mkdir(outputDir, { recursive: true });
  await writeFile(join(outputDir, "api-contract-report.json"), JSON.stringify(report, null, 2));
  console.error(error);
  process.exitCode = 1;
}
