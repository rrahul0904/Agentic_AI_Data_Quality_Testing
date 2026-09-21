/**
 * Measure persisted, read-only routes without invoking connector refreshes or
 * live jobs.  Run against the production UI (`next start`) for reproducible
 * API timings; the route itself is the browser-facing request boundary.
 */

const uiBase = (process.env.ADQ_UI_URL || "http://127.0.0.1:3020").replace(/\/$/, "");
const projectId = process.env.ADQ_PROJECT_ID || "data-quality-testing-beta";
const environment = process.env.ADQ_ENVIRONMENT || "development";
const rounds = Number(process.env.ADQ_PERF_ROUNDS || 5);
const concurrencyLevels = [1, 5, 10, 25];
const routes = [
  `/api/operations?mode=summary&project_id=${encodeURIComponent(projectId)}&environment=${encodeURIComponent(environment)}`,
  `/api/monitoring?page=1&page_size=25&project_id=${encodeURIComponent(projectId)}&environment=${encodeURIComponent(environment)}`,
];

function percentile(values, fraction) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))];
}

async function readRoute(path) {
  const started = performance.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(`${uiBase}${path}`, { cache: "no-store", signal: controller.signal });
    const body = await response.text();
    return { ok: response.ok, status: response.status, ms: performance.now() - started, bytes: Buffer.byteLength(body) };
  } catch (error) {
    return { ok: false, status: 0, ms: performance.now() - started, bytes: 0, error: error instanceof Error ? error.message : "request failed" };
  } finally {
    clearTimeout(timer);
  }
}

const results = [];
for (const level of concurrencyLevels) {
  for (const path of routes) {
    const samples = [];
    for (let round = 0; round < rounds; round += 1) {
      samples.push(...await Promise.all(Array.from({ length: level }, () => readRoute(path))));
    }
    const durations = samples.map((item) => item.ms);
    results.push({
      route: path.split("?")[0],
      concurrency: level,
      samples: samples.length,
      errors: samples.filter((item) => !item.ok).length,
      status_codes: [...new Set(samples.map((item) => item.status))].sort((a, b) => a - b),
      p50_ms: percentile(durations, 0.5),
      p95_ms: percentile(durations, 0.95),
      max_ms: durations.length ? Math.max(...durations) : null,
      max_payload_bytes: samples.length ? Math.max(...samples.map((item) => item.bytes)) : 0,
    });
  }
}

process.stdout.write(`${JSON.stringify({
  measured_at: new Date().toISOString(),
  ui_base: uiBase,
  project_id: projectId,
  environment,
  rounds,
  read_only: true,
  live_connector_operations_performed: false,
  method: "fetch from the browser-facing UI route with a 10s cancellation deadline; p50/p95/max over completed requests",
  results,
}, null, 2)}\n`);
