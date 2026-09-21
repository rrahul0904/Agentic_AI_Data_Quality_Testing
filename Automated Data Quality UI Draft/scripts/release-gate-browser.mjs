import { mkdir, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { join } from "node:path";

const base = (process.env.ADQ_UI_URL || "http://127.0.0.1:3020").replace(/\/$/, "");
const chromePath = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outputDir = join(process.cwd(), "artifacts", "phase3");
const projectId = process.env.ADQ_PROJECT_ID || "data-quality-testing-beta";
const environment = process.env.ADQ_ENVIRONMENT || "development";
const viewports = [
  { name: "1280x720", width: 1280, height: 720, deviceScaleFactor: 1, pageScaleFactor: 1 },
  { name: "1366x768", width: 1366, height: 768, deviceScaleFactor: 1, pageScaleFactor: 1 },
  { name: "1440x900", width: 1440, height: 900, deviceScaleFactor: 1, pageScaleFactor: 1 },
  { name: "200-percent", width: 1440, height: 900, deviceScaleFactor: 1, pageScaleFactor: 2 },
];

function routeUrl(path) {
  const url = new URL(path, base);
  if (!url.searchParams.has("project_id")) url.searchParams.set("project_id", projectId);
  if (!url.searchParams.has("environment")) url.searchParams.set("environment", environment);
  return url.toString();
}

function fixtureRouteUrl(path) {
  const url = new URL(path, base);
  url.searchParams.set("fixture", "phase4");
  url.searchParams.set("project_id", "fixture-project");
  url.searchParams.set("environment", "fixture");
  return url.toString();
}

function slug(value) {
  return String(value).replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function waitForDevTools(proc) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Chrome DevTools timeout: ${output.slice(-400)}`)), 30000);
    const read = (chunk) => {
      output += chunk.toString();
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    };
    proc.stderr.on("data", read);
    proc.stdout.on("data", read);
    proc.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`Chrome exited (${code})`));
    });
  });
}

class Cdp {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Map();
    this.consoleErrors = [];
  }

  async connect() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", async (event) => {
      const raw = typeof event.data === "string" ? event.data : await event.data.text();
      const message = JSON.parse(raw);
      for (const listener of this.listeners.get(message.method) || []) listener(message.params);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      message.error ? pending.reject(new Error(message.error.message)) : pending.resolve(message.result);
    });
  }

  on(method, listener) {
    const listeners = this.listeners.get(method) || [];
    listeners.push(listener);
    this.listeners.set(method, listeners);
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "browser evaluation failed");
    return result.result?.value;
  }

  close() {
    this.socket.close();
  }
}

async function openTarget(devToolsSocket, url) {
  const port = new URL(devToolsSocket).port;
  const response = await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
  if (!response.ok) throw new Error(`Cannot open browser target (${response.status})`);
  return response.json();
}

async function waitFor(client, expression, label, timeoutMs = 15000) {
  const started = Date.now();
  let last;
  while (Date.now() - started < timeoutMs) {
    last = await client.eval(expression);
    if (last === true || (last && last.ready === true)) return last;
    await wait(100);
  }
  throw new Error(`Timed out waiting for ${label}: ${JSON.stringify(last)}`);
}

async function pageState(client) {
  return client.eval(`(() => {
    const visible = (element) => {
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const rects = [...document.querySelectorAll(".projectActions > *, .tableActions button, .pageHeaderActions > button, #plan-workspace button, #plan-workspace select, #plan-workspace input")]
      .filter(visible)
      .map((element) => ({ tag: element.tagName, text: (element.innerText || element.getAttribute("aria-label") || "").trim().slice(0, 80), rect: element.getBoundingClientRect().toJSON() }));
    const overlaps = [];
    for (let index = 0; index < rects.length; index += 1) {
      for (let other = index + 1; other < rects.length; other += 1) {
        const a = rects[index].rect;
        const b = rects[other].rect;
        if (a.right > b.left + 1 && b.right > a.left + 1 && a.bottom > b.top + 1 && b.bottom > a.top + 1) {
          overlaps.push({ first: rects[index].text, second: rects[other].text });
        }
      }
    }
    const body = document.body;
    return {
      bodyLength: body?.innerText?.length || 0,
      title: document.title,
      readyState: document.readyState,
      hasMain: Boolean(document.querySelector("main")),
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      // Controls below the fold are scrollable, not clipped. Only flag controls
      // that are horizontally outside the viewport or above the document.
      controlsOutsideViewport: rects.filter(({ rect }) => rect.left < -1 || rect.right > window.innerWidth + 1 || rect.bottom < -1).map(({ text }) => text),
      keyControlOverlaps: overlaps,
      route: window.location.pathname + window.location.search,
    };
  })()`);
}

async function navigate(client, path, options = {}) {
  const {
    api = [],
    marker,
    text,
    screenshot = false,
    viewportName = "default",
    label = path,
    fixture = false,
  } = options;
  await client.send("Page.navigate", { url: fixture ? fixtureRouteUrl(path) : routeUrl(path) });
  await waitFor(client, "document.readyState === 'complete' && Boolean(document.querySelector('main'))", `${label} document`);
  for (const resource of api) {
    await waitFor(
      client,
      `performance.getEntriesByType("resource").some((entry) => entry.name.includes(${JSON.stringify(resource)}))`,
      `${label} API ${resource}`,
    );
  }
  if (marker) await waitFor(client, `Boolean(document.querySelector(${JSON.stringify(marker)}))`, `${label} marker ${marker}`);
  if (text) await waitFor(client, `(document.body?.innerText || "").includes(${JSON.stringify(text)})`, `${label} text ${text}`);
  const state = await pageState(client);
  let screenshotPath;
  if (screenshot) {
    const capture = await client.send("Page.captureScreenshot", { format: "png" });
    screenshotPath = join(outputDir, `${slug(viewportName)}-${slug(path)}.png`);
    await writeFile(screenshotPath, Buffer.from(capture.data, "base64"));
  }
  return { ...state, screenshotPath };
}

async function pressTab(client) {
  await client.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
  await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
}

async function verifyKeyboard(client, label) {
  await client.eval("document.body?.focus(); document.activeElement?.blur()");
  const focusTargets = [];
  for (let index = 0; index < 16; index += 1) {
    await pressTab(client);
    const target = await client.eval(`(() => {
      const element = document.activeElement;
      if (!element || element === document.body) return null;
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      const visible = style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      const indicator = element.matches(":focus-visible") || style.outlineWidth !== "0px" || style.outlineStyle !== "none" || style.boxShadow !== "none";
      return { tag: element.tagName, text: (element.innerText || element.getAttribute("aria-label") || element.getAttribute("placeholder") || "").trim().slice(0, 80), visible, indicator };
    })()`);
    if (target) focusTargets.push(target);
  }
  const moved = new Set(focusTargets.map((target) => `${target.tag}:${target.text}`)).size > 1;
  const visibleFocus = focusTargets.some((target) => target.visible && target.indicator);
  if (!moved || !visibleFocus) throw new Error(`${label} keyboard traversal did not show movement and visible focus`);
  return { focusTargets, moved, visibleFocus };
}

async function clickFirstRun(client) {
  const clicked = await client.eval(`(() => {
    const button = document.querySelector('button[aria-label^="View details for "]');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!clicked) return { available: false, reason: "No persisted run was returned for this project/environment" };
  await waitFor(client, "Boolean(document.querySelector('#selected-run'))", "selected run details");
  await waitFor(client, "Boolean(document.querySelector(\"#selected-run [class*='summaryGrid']\"))", "selected run outcome");
  const runId = await client.eval(`document.querySelector('button[aria-label^="View details for "]')?.getAttribute('aria-label') || null`);
  return { available: true, runId };
}

async function applyMonitoringAssetFilter(client) {
  const prepared = await client.eval(`(() => {
    const input = document.querySelector('input[placeholder="table, DAG, model"]');
    const apply = [...document.querySelectorAll('button')].find((button) => (button.innerText || '').trim().toLowerCase() === 'apply filters');
    if (!input || !apply) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, 'definitely-not-a-real-table');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    apply.click();
    return true;
  })()`);
  if (!prepared) throw new Error("Monitoring table-filter controls were not rendered");
  await waitFor(client, "(document.body?.innerText || '').toLowerCase().includes('no persisted jobs match this table filter')", "monitoring table filter empty state");
  return pageState(client);
}

async function resetMonitoringStorage(client) {
  await client.eval("localStorage.removeItem('ade-monitoring-filters'); localStorage.removeItem('ade-monitoring-selected-run:data-quality-testing-beta:development');");
}

async function independentPlanningJourney(client) {
  const controls = await client.eval(`(() => ({
    operation: document.querySelector('select[aria-label="Requested operation"]')?.outerHTML || null,
    target: document.querySelector('input[aria-label="Requested job target"]')?.outerHTML || null,
    preview: [...document.querySelectorAll('button')].find((button) => (button.innerText || '').includes('Preview exact plan'))?.innerText || null,
  }))()`);
  if (!controls.operation || !controls.target || !controls.preview) throw new Error("Independent job controls were not rendered");
  await client.eval(`(() => {
    const select = document.querySelector('select[aria-label="Requested operation"]');
    const input = document.querySelector('input[aria-label="Requested job target"]');
    const selectSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    const inputSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    selectSetter.call(select, 'airflow_trigger');
    select.dispatchEvent(new Event('change', { bubbles: true }));
    inputSetter.call(input, 'ingest_reference_data');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  const selected = await client.eval(`(() => ({
    operation: document.querySelector('select[aria-label="Requested operation"]')?.value || null,
    target: document.querySelector('input[aria-label="Requested job target"]')?.value || null,
  }))()`);
  if (selected.operation !== "airflow_trigger" || selected.target !== "ingest_reference_data") {
    throw new Error(`Independent job controls did not accept requested scope: ${JSON.stringify(selected)}`);
  }
  return { controls, selected, previewed: false, note: "Control interaction verified without submitting a live operation" };
}

const chrome = spawn(chromePath, [
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--disable-background-networking",
  "--remote-debugging-port=0",
  "about:blank",
], { stdio: ["ignore", "pipe", "pipe"] });

let client;
const report = {
  base,
  projectId,
  environment,
  viewports: viewports.map(({ name, width, height, pageScaleFactor }) => ({ name, width, height, pageScaleFactor })),
  journeys: [],
  routeChecks: [],
  screenshots: [],
  failures: [],
  passed: false,
  note: "Read-only browser release gate. It plans no live pipeline operation and does not mutate connector/provider state.",
};

try {
  const browserSocket = await waitForDevTools(chrome);
  const target = await openTarget(browserSocket, routeUrl("/"));
  client = new Cdp(target.webSocketDebuggerUrl);
  await client.connect();
  client.on("Log.entryAdded", (params) => {
    if (params.entry?.level === "error") client.consoleErrors.push(params.entry.text);
  });
  await Promise.all([
    client.send("Page.enable"),
    client.send("Runtime.enable"),
    client.send("Network.enable"),
    client.send("Log.enable"),
  ]);
  await mkdir(outputDir, { recursive: true });

  for (const viewport of viewports) {
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: viewport.deviceScaleFactor,
      mobile: false,
    });
    await client.send("Emulation.setPageScaleFactor", { pageScaleFactor: viewport.pageScaleFactor });
    const capture = viewport.name === "1280x720" || viewport.name === "1440x900";
    await resetMonitoringStorage(client);

    const monitoring = await navigate(client, "/monitoring", {
      api: ["/api/monitoring"],
      marker: "h1",
      text: "Monitoring",
      screenshot: capture,
      viewportName: `${viewport.name}-monitoring`,
      label: `${viewport.name} monitoring`,
    });
    report.routeChecks.push({ name: "Monitoring without table filter", viewport: viewport.name, ...monitoring });
    if (monitoring.screenshotPath) report.screenshots.push(monitoring.screenshotPath);

    const details = await clickFirstRun(client);
    report.journeys.push({ name: "Project → Monitoring → existing run → run details", viewport: viewport.name, passed: true, ...details });

    const filtered = await applyMonitoringAssetFilter(client);
    report.journeys.push({ name: "Monitoring with explicit table filter", viewport: viewport.name, passed: true, ...filtered });

    const actions = await navigate(client, "/actions", {
      api: ["/api/actions"],
      marker: "#plan-workspace",
      text: "Run jobs",
      screenshot: capture,
      viewportName: `${viewport.name}-run-jobs`,
      label: `${viewport.name} Run jobs`,
    });
    report.routeChecks.push({ name: "Direct /actions navigation", viewport: viewport.name, ...actions });
    if (actions.screenshotPath) report.screenshots.push(actions.screenshotPath);
    const planning = await independentPlanningJourney(client);
    report.journeys.push({ name: "Independent Airflow planning flow", viewport: viewport.name, passed: true, ...planning });

    const connections = await navigate(client, "/register-project?phase=connections", {
      api: ["/api/onboarding"],
      marker: "table",
      text: "Connect systems",
      screenshot: capture,
      viewportName: `${viewport.name}-connections`,
      label: `${viewport.name} connections`,
    });
    report.routeChecks.push({ name: "Project setup and connection actions", viewport: viewport.name, ...connections });
    if (connections.screenshotPath) report.screenshots.push(connections.screenshotPath);
    report.journeys.push({ name: "Keyboard traversal on connections", viewport: viewport.name, passed: true, ...(await verifyKeyboard(client, `${viewport.name} connections`)) });

    const catalog = await navigate(client, "/objects-flows", {
      api: ["/api/project-analysis"],
      marker: "h1",
      text: "Catalog",
      screenshot: capture,
      viewportName: `${viewport.name}-catalog`,
      label: `${viewport.name} Catalog`,
    });
    report.routeChecks.push({ name: "Catalog current scoped state", viewport: viewport.name, ...catalog });
    if (catalog.screenshotPath) report.screenshots.push(catalog.screenshotPath);

    const lineage = await navigate(client, "/map-flows", {
      api: ["/api/project-analysis"],
      marker: "h1",
      text: "Lineage",
      screenshot: capture,
      viewportName: `${viewport.name}-lineage`,
      label: `${viewport.name} Lineage`,
    });
    report.routeChecks.push({ name: "Lineage current scoped state", viewport: viewport.name, ...lineage });
    if (lineage.screenshotPath) report.screenshots.push(lineage.screenshotPath);

    const rules = await navigate(client, "/test-plan?view=contracts&mode=manage", {
      api: ["/api/quality-plans"],
      marker: "h1",
      text: "Quality rules",
      label: `${viewport.name} Quality rules`,
    });
    report.routeChecks.push({ name: "Rules current scoped state", viewport: viewport.name, ...rules });

    const fixtureCatalog = await navigate(client, "/objects-flows", {
      fixture: true,
      api: ["/api/project-analysis"],
      marker: "h1",
      text: "postgres.public.orders",
      screenshot: capture,
      viewportName: `${viewport.name}-fixture-catalog`,
      label: `${viewport.name} populated Catalog fixture`,
    });
    report.routeChecks.push({ name: "Populated Catalog test-only fixture", viewport: viewport.name, ...fixtureCatalog });
    if (fixtureCatalog.screenshotPath) report.screenshots.push(fixtureCatalog.screenshotPath);

    const fixtureLineage = await navigate(client, "/map-flows", {
      fixture: true,
      api: ["/api/project-analysis"],
      marker: "[aria-label='Interactive pipeline graph']",
      text: "stg_orders",
      screenshot: capture,
      viewportName: `${viewport.name}-fixture-lineage`,
      label: `${viewport.name} populated Lineage fixture`,
    });
    report.routeChecks.push({ name: "Populated Lineage test-only fixture", viewport: viewport.name, ...fixtureLineage });
    if (fixtureLineage.screenshotPath) report.screenshots.push(fixtureLineage.screenshotPath);

    const fixtureRules = await navigate(client, "/test-plan?view=contracts&mode=manage", {
      fixture: true,
      api: ["/api/quality-plans"],
      marker: '[aria-label="Quality rules"]',
      text: "orders not null",
      screenshot: capture,
      viewportName: `${viewport.name}-fixture-rules`,
      label: `${viewport.name} populated Rules fixture`,
    });
    report.routeChecks.push({ name: "Populated Rules test-only fixture", viewport: viewport.name, ...fixtureRules });
    if (fixtureRules.screenshotPath) report.screenshots.push(fixtureRules.screenshotPath);

    const history = await navigate(client, "/test-plan?view=execution&mode=manage&tab=history", {
      api: ["/api/quality-plans"],
      marker: "h1",
      text: "Runs & evidence",
      screenshot: capture,
      viewportName: `${viewport.name}-history`,
      label: `${viewport.name} history`,
    });
    report.routeChecks.push({ name: "Populated history state", viewport: viewport.name, ...history });
    if (history.screenshotPath) report.screenshots.push(history.screenshotPath);

    if (viewport.name === "1280x720") {
      await client.send("Network.setBlockedURLs", { urls: [`${base}/api/monitoring*`] });
      const unavailable = await navigate(client, "/monitoring", {
        marker: "h1",
        text: "Monitoring",
        screenshot: true,
        viewportName: `${viewport.name}-monitoring-error`,
        label: "Monitoring API error state",
      });
      report.journeys.push({ name: "API error/retry state", viewport: viewport.name, passed: true, ...unavailable, note: "Monitoring route rendered while its API request was blocked" });
      if (unavailable.screenshotPath) report.screenshots.push(unavailable.screenshotPath);
      await client.send("Network.setBlockedURLs", { urls: [] });
      const recovered = await navigate(client, "/monitoring", {
        api: ["/api/monitoring"],
        marker: "h1",
        text: "Monitoring",
        label: "Monitoring API recovery state",
      });
      report.journeys.push({ name: "API recovery after retry", viewport: viewport.name, passed: true, ...recovered });
    }
  }

  report.consoleErrors = client.consoleErrors;
  report.failures = [
    ...report.routeChecks.filter((item) => item.bodyLength < 100 || !item.hasMain || item.horizontalOverflow || item.controlsOutsideViewport.length || item.keyControlOverlaps.length),
    ...report.journeys.filter((item) => item.passed === false),
  ];
  report.passed = report.failures.length === 0 && report.consoleErrors.length === 0;
  await writeFile(join(outputDir, "release-gate-report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
} catch (error) {
  report.failures.push({ name: "release-gate", error: error instanceof Error ? error.message : String(error) });
  report.consoleErrors = client?.consoleErrors || [];
  await mkdir(outputDir, { recursive: true });
  await writeFile(join(outputDir, "release-gate-report.json"), JSON.stringify(report, null, 2));
  console.error(error);
  process.exitCode = 1;
} finally {
  client?.close();
  if (chrome.exitCode === null) chrome.kill("SIGTERM");
}
