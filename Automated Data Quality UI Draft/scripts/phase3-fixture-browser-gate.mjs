import { spawn } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

/**
 * Phase 3 rendered-DOM verification.
 *
 * This launches an isolated local Next server with the explicitly gated Phase
 * 4 fixture scope. It does not connect to the working project, backend,
 * adapters, or an AI provider. The gate purposely never clicks an operation
 * that could issue a POST request.
 */
const port = Number(process.env.ADQ_PHASE3_FIXTURE_PORT || 3033);
const base = `http://127.0.0.1:${port}`;
const chromePath = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const viewports = [
  { name: "1280x720", width: 1280, height: 720 },
  { name: "1440x900", width: 1440, height: 900 },
];
const fixtureScope = { fixture: "phase4", project_id: "fixture-project", environment: "fixture" };

function fixtureUrl(pathname) {
  const url = new URL(pathname, base);
  for (const [key, value] of Object.entries(fixtureScope)) url.searchParams.set(key, value);
  return url.toString();
}

function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function startFixtureServer() {
  const child = spawn("node_modules/.bin/next", ["dev", "-p", String(port)], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      ADQ_UI_TEST_FIXTURES: "1",
      ADE_NEXT_DIST_DIR: ".next-phase3-fixture",
      NEXT_TELEMETRY_DISABLED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  return child;
}

async function waitForServer(server) {
  let output = "";
  const collect = (chunk) => { output += String(chunk); };
  server.stdout.on("data", collect);
  server.stderr.on("data", collect);
  const started = Date.now();
  while (Date.now() - started < 30000) {
    try {
      const response = await fetch(fixtureUrl("/api/onboarding"), { signal: AbortSignal.timeout(1000) });
      if (response.ok && response.headers.get("X-ADQ-Test-Fixture") === "phase4") return;
    } catch { /* Server has not started yet. */ }
    if (server.exitCode !== null) throw new Error(`Fixture UI server exited (${server.exitCode}): ${output.slice(-600)}`);
    await wait(120);
  }
  throw new Error(`Fixture UI server did not become ready: ${output.slice(-600)}`);
}

function waitForDevTools(chrome) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Chrome DevTools timeout: ${output.slice(-500)}`)), 30000);
    const receive = (chunk) => {
      output += String(chunk);
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    };
    chrome.stdout.on("data", receive);
    chrome.stderr.on("data", receive);
    chrome.once("exit", (code) => { clearTimeout(timer); reject(new Error(`Chrome exited (${code}): ${output.slice(-500)}`)); });
  });
}

class Cdp {
  constructor(socketUrl) {
    this.socket = new WebSocket(socketUrl);
    this.nextId = 0;
    this.pending = new Map();
    this.listeners = new Map();
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
      const request = this.pending.get(message.id);
      if (!request) return;
      this.pending.delete(message.id);
      message.error ? request.reject(new Error(message.error.message)) : request.resolve(message.result);
    });
  }

  on(method, listener) { this.listeners.set(method, [...(this.listeners.get(method) || []), listener]); }

  send(method, params = {}) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const result = await this.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
    return result.result?.value;
  }

  close() { this.socket.close(); }
}

async function openTarget(devToolsUrl, url) {
  const devToolsPort = new URL(devToolsUrl).port;
  const response = await fetch(`http://127.0.0.1:${devToolsPort}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
  if (!response.ok) throw new Error(`Unable to create browser tab: ${response.status}`);
  return response.json();
}

async function waitFor(client, expression, label, timeout = 20000) {
  const started = Date.now();
  let last;
  while (Date.now() - started < timeout) {
    last = await client.eval(expression);
    if (last) return last;
    await wait(100);
  }
  throw new Error(`Timed out waiting for ${label}: ${JSON.stringify(last)}`);
}

async function setViewport(client, viewport) {
  await client.send("Emulation.setDeviceMetricsOverride", {
    width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: false,
  });
}

async function pageFacts(client) {
  return client.eval(`(() => {
    const interactive = [...document.querySelectorAll('a, button, input, select, summary')];
    const visible = (node) => {
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
    };
    const controls = interactive.filter(visible).map((node) => {
      const box = node.getBoundingClientRect();
      return { name: (node.getAttribute('aria-label') || node.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 100), left: box.left, right: box.right, top: box.top, bottom: box.bottom };
    });
    return {
      content: document.body?.innerText || '',
      hasMain: Boolean(document.querySelector('main')),
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      outsideViewport: controls.filter((item) => item.left < -1 || item.right > window.innerWidth + 1),
      controlCount: controls.length,
      ariaBusy: [...document.querySelectorAll('[aria-busy="true"]')].length,
      errorRoles: [...document.querySelectorAll('[role="alert"], [role="status"]')].map((node) => node.textContent?.trim()).filter(Boolean),
    };
  })()`);
}

async function navigate(client, path, marker, label) {
  await client.send("Page.navigate", { url: fixtureUrl(path) });
  await waitFor(client, "document.readyState === 'complete' && Boolean(document.querySelector('main'))", `${label} shell`);
  await waitFor(client, marker, `${label} fixture marker`);
  return pageFacts(client);
}

async function pressTab(client) {
  await client.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
  await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
}

async function keyboardFacts(client) {
  await client.eval("document.activeElement?.blur(); document.body?.focus();");
  const targets = [];
  for (let index = 0; index < 12; index += 1) {
    await pressTab(client);
    const target = await client.eval(`(() => {
      const node = document.activeElement;
      if (!node || node === document.body) return null;
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        name: (node.getAttribute('aria-label') || node.textContent || node.getAttribute('placeholder') || '').trim().replace(/\\s+/g, ' ').slice(0, 80),
        visible: box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none',
        focusVisible: node.matches(':focus-visible'),
      };
    })()`);
    if (target) targets.push(target);
  }
  return {
    targets,
    moved: new Set(targets.map((target) => target.name)).size > 1,
    visibleFocus: targets.some((target) => target.visible && target.focusVisible),
  };
}

function assert(name, condition, detail, report) {
  const result = { name, passed: Boolean(condition), detail };
  report.checks.push(result);
  if (!result.passed) report.failures.push(result);
}

const report = { fixtureScope, viewports, checks: [], failures: [], skipped: [], requests: [], consoleErrors: [], note: "Fixture-only Phase 3 browser verification; no provider, pipeline, or working-project requests are permitted." };
let server;
let chrome;
let client;

try {
  server = startFixtureServer();
  await waitForServer(server);
  const apiChecks = [
    ["Project scope", "/api/project-scope", (value) => value.available_source_tables === 15 && value.onboarded_source_tables === 1 && value.accepted_discovered_assets === 3 && value.analyzed_source_rooted_flows === 1],
    ["Source onboarding", "/api/data-onboarding", (value) => value.status === "CONNECTED" && value.tables?.some((item) => item.table === "orders")],
    ["Catalog discovery", "/api/project-analysis?view=compact", (value) => value.report?.summary?.assets === 3],
    ["Lineage discovery", "/api/project-analysis?view=compact", (value) => value.report?.pipelines?.length === 1],
    ["Quality plan state", "/api/quality-plans", (value) => value.plan?.status === "APPROVED" && Array.isArray(value.runs)],
    ["Run Jobs workspace", "/api/actions", (value) => value.source_table_scope_id === "fixture_orders" && value.runs?.items?.length === 0],
    ["Connection readiness", "/api/demo/readiness", (value) => value.readiness?.length >= 4 && value.readiness.every((item) => item.status === "READY")],
    ["Monitoring history", "/api/monitoring", (value) => value.items?.[0]?.verification_status === "VERIFIED"],
    ["Reconciliation history", "/api/reconciliation", (value) => value.history?.items?.length === 1 && value.catalogs?.source?.length === 1],
    ["Ask AI scoped status", "/api/agent", (value) => value.workspace?.projectId === "fixture-project"],
  ];
  for (const [name, pathname, predicate] of apiChecks) {
    const response = await fetch(fixtureUrl(pathname));
    const value = await response.json().catch(() => ({}));
    assert(`API contract: ${name}`, response.ok && response.headers.get("X-ADQ-Test-Fixture") === "phase4" && predicate(value), { status: response.status, fixture: response.headers.get("X-ADQ-Test-Fixture"), keys: Object.keys(value) }, report);
  }
  const planResponse = await fetch(fixtureUrl("/api/actions"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "plan", intent: "Run only dbt model stg_orders", mode: "single_job", operationKind: "dbt_execute", requestedTarget: "stg_orders" }) });
  const planValue = await planResponse.json().catch(() => ({}));
  assert("API contract: Run Jobs creates preview-only fixture plan", planResponse.ok && planValue.plan?.state === "PREVIEW_ONLY" && planValue.plan?.steps?.length === 1, { status: planResponse.status, state: planValue.plan?.state, steps: planValue.plan?.steps?.length }, report);
  const askResponse = await fetch(fixtureUrl("/api/agent"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: "Summarize the fixture orders workflow" }) });
  const askValue = await askResponse.json().catch(() => ({}));
  assert("API contract: Ask AI fixture answer is human-readable and clearly test-only", askResponse.ok && String(askValue.answer ?? "").includes("This is test content, not live evidence"), { status: askResponse.status, answer: askValue.answer }, report);
  const profile = await mkdtemp(join(tmpdir(), "adq-phase3-chrome-"));
  chrome = spawn(chromePath, ["--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "pipe", "pipe"] });
  const devTools = await waitForDevTools(chrome);
  const target = await openTarget(devTools, fixtureUrl("/objects-flows"));
  client = new Cdp(target.webSocketDebuggerUrl);
  await client.connect();
  client.on("Log.entryAdded", (event) => { if (event.entry?.level === "error") report.consoleErrors.push(event.entry.text); });
  client.on("Network.requestWillBeSent", (event) => {
    const request = { url: String(event.request?.url || ""), method: String(event.request?.method || "GET") };
    report.requests.push(request);
  });
  await Promise.all([client.send("Page.enable"), client.send("Runtime.enable"), client.send("Network.enable"), client.send("Log.enable")]);
  // Every scoped page API is served from fixture-only branches. Any API
  // request without the explicit fixture scope is rejected by the gate below.

  for (const viewport of viewports) {
    await setViewport(client, viewport);
    const catalog = await navigate(client, "/objects-flows", "(document.body?.innerText || '').includes('postgres.public.orders')", `${viewport.name} catalog`);
    assert(`${viewport.name}: populated catalog has semantic search`, await client.eval("Boolean(document.querySelector('input[aria-label=\\\"Search objects\\\"]'))"), catalog, report);
    assert(`${viewport.name}: populated catalog has no horizontal overflow`, !catalog.horizontalOverflow && catalog.outsideViewport.length === 0, catalog, report);

    const emptyPrepared = await client.eval(`(() => {
      const input = document.querySelector('input[aria-label="Search objects"]');
      if (!input) return false;
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      set.call(input, '__phase3_no_match__');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    assert(`${viewport.name}: catalog filter control is usable`, emptyPrepared, {}, report);
    await waitFor(client, "(document.body?.innerText || '').includes('No objects match these filters.')", `${viewport.name} catalog empty state`);
    const empty = await pageFacts(client);
    assert(`${viewport.name}: catalog empty state remains within viewport`, !empty.horizontalOverflow && empty.outsideViewport.length === 0, empty, report);

    const lineage = await navigate(client, "/map-flows", "Boolean(document.querySelector('[aria-label=\\\"Interactive pipeline graph\\\"]'))", `${viewport.name} lineage`);
    assert(`${viewport.name}: populated lineage graph is rendered`, (lineage.content || '').includes('stg_orders'), lineage, report);
    assert(`${viewport.name}: lineage controls have no horizontal overflow`, !lineage.horizontalOverflow && lineage.outsideViewport.length === 0, lineage, report);

    const rules = await navigate(client, "/test-plan?view=contracts&mode=manage", "Boolean(document.querySelector('[aria-label=\\\"Quality rules\\\"]'))", `${viewport.name} rules`);
    assert(`${viewport.name}: populated rules expose a semantic list`, (rules.content || '').includes('orders not null'), rules, report);
    assert(`${viewport.name}: rules controls have no horizontal overflow`, !rules.horizontalOverflow && rules.outsideViewport.length === 0, rules, report);

    const focus = await keyboardFacts(client);
    assert(`${viewport.name}: keyboard focus moves across fixture controls`, focus.moved && focus.visibleFocus, focus, report);

    const history = await navigate(client, "/test-plan?view=execution&mode=manage&tab=history", "(document.body?.innerText || '').includes('Run history') && Boolean(document.querySelector('a[href*=\"run_id=\"]'))", `${viewport.name} run history`);
    assert(`${viewport.name}: populated history lists persisted runs`, history.content.includes("run history") || history.content.includes("Run history"), history, report);
    const clickedRunId = await client.eval(`(() => {
      const link = document.querySelector('a[href*="run_id="]');
      if (!link) return null;
      const runId = new URL(link.href).searchParams.get('run_id');
      link.click();
      return runId;
    })()`);
    assert(`${viewport.name}: history row is clickable`, Boolean(clickedRunId), { clickedRunId }, report);
    await waitFor(client, `Boolean(document.querySelector('#selected-run-title')) && (document.body?.innerText || '').includes(${JSON.stringify(clickedRunId)}) && (document.body?.innerText || '').includes('Check results')`, `${viewport.name} selected run details`);
    const selectedRun = await pageFacts(client);
    assert(`${viewport.name}: selected run shows exact result`, selectedRun.content.includes(clickedRunId) && selectedRun.content.includes("Evidence source"), selectedRun, report);
    const direct = await navigate(client, `/test-plan?view=execution&mode=manage&tab=history&run_id=${encodeURIComponent(clickedRunId)}`, "Boolean(document.querySelector('#selected-run-title')) && (document.body?.innerText || '').includes('Check results')", `${viewport.name} direct run details`);
    assert(`${viewport.name}: direct run link survives refresh`, direct.content.includes(clickedRunId) && direct.content.includes("Evidence source"), direct, report);

    const onboarding = await navigate(client, "/register-project?phase=overview", "(document.body?.innerText || '').includes('orders')", `${viewport.name} onboarding`);
    assert(`${viewport.name}: onboarding keeps fixture source selection visible`, onboarding.content.includes("public.orders"), onboarding, report);
    assert(`${viewport.name}: onboarding responsive`, !onboarding.horizontalOverflow && onboarding.outsideViewport.length === 0, onboarding, report);
    const monitoring = await navigate(client, "/monitoring", "(document.body?.innerText || '').includes('fixture_action_completed')", `${viewport.name} monitoring`);
    assert(`${viewport.name}: monitoring page renders scoped fixture state`, monitoring.hasMain && !monitoring.horizontalOverflow, monitoring, report);
    await client.send("Page.reload");
    await waitFor(client, "document.readyState === 'complete' && document.body.innerText.includes('fixture_action_completed')", `${viewport.name} monitoring reload`);
    const reloadedMonitoring = await pageFacts(client);
    assert(`${viewport.name}: browser reload preserves rendered scoped page state`, reloadedMonitoring.hasMain && !reloadedMonitoring.horizontalOverflow, reloadedMonitoring, report);
    const reconciliation = await navigate(client, "/reconciliation", "(document.body?.innerText || '').includes('1 OF 1 RESULTS')", `${viewport.name} reconciliation`);
    assert(`${viewport.name}: reconciliation history renders without executing a comparison`, reconciliation.content.includes("1 OF 1 RESULTS") && !reconciliation.horizontalOverflow && reconciliation.outsideViewport.length === 0, reconciliation, report);
    const askAi = await navigate(client, "/agent", "(document.body?.innerText || '').includes('Ask AI')", `${viewport.name} Ask AI`);
    assert(`${viewport.name}: Ask AI page loads for fixture scope`, askAi.hasMain && !askAi.horizontalOverflow, askAi, report);
    await waitFor(client, "document.body.innerText.includes('Fixture response: orders is represented')", `${viewport.name} rendered fixture Ask AI answer`);
    const askAnswer = await pageFacts(client);
    assert(`${viewport.name}: Ask AI renders a readable scoped answer`, askAnswer.content.includes("This is test content, not live evidence.") && !askAnswer.horizontalOverflow && askAnswer.outsideViewport.length === 0, askAnswer, report);
    const actions = await navigate(client, "/actions", "(document.body?.innerText || '').toLowerCase().includes('preview only') && Boolean(document.querySelector('textarea[aria-label=\"Execution request\"]'))", `${viewport.name} Run Jobs`);
    const previewed = actions.content.toLowerCase().includes("preview only") && actions.content.includes("stg_orders");
    assert(`${viewport.name}: Run Jobs preview is visible and not executed`, previewed && actions.hasMain, { previewed }, report);
    const approveEnabled = await client.eval(`![...document.querySelectorAll('button')].some(item => /Approve once|Execute approved plan/.test(item.textContent || '') && !item.disabled)`);
    assert(`${viewport.name}: no enabled approval/execution control before human steps`, approveEnabled, { approveEnabled }, report);
  }

  // Block only the fixture analysis endpoint; this triggers a genuine client
  // fetch failure without allowing a request to reach any provider.
  await client.send("Network.setBlockedURLs", { urls: [`${base}/api/project-analysis*`] });
  await setViewport(client, viewports[0]);
  const error = await navigate(client, "/objects-flows", "(document.body?.innerText || '').includes('No catalog analysis yet')", "fixture analysis error");
  await waitFor(client, "(document.body?.innerText || '').includes('Failed to fetch')", "fixture analysis error message");
  assert("fixture analysis error remains distinguishable from populated data", (error.content || '').includes('No catalog analysis yet'), error, report);
  await client.send("Network.setBlockedURLs", { urls: [] });

  const unsafeRequests = report.requests.filter((request) => {
    const url = new URL(request.url);
    if (url.protocol === "data:") return false;
    if (url.origin !== base) return true;
    if (url.pathname.startsWith("/api/") && url.searchParams.get("fixture") !== "phase4") return true;
    if (["PUT", "PATCH", "DELETE"].includes(request.method)) return true;
    return request.method === "POST" && !["/api/actions", "/api/agent"].includes(url.pathname);
  });
  assert("fixture browser gate made no external network request or unexpected mutation", unsafeRequests.length === 0, { unsafeRequests }, report);
  assert("fixture browser gate observed no console errors", report.consoleErrors.length === 0, { consoleErrors: report.consoleErrors }, report);
} catch (error) {
  report.failures.push({ name: "fixture browser gate", passed: false, detail: error instanceof Error ? error.message : String(error) });
} finally {
  client?.close();
  if (chrome?.exitCode === null) chrome.kill("SIGTERM");
  if (server?.exitCode === null) server.kill("SIGTERM");
}

report.passed = report.failures.length === 0;
console.log(JSON.stringify(report, null, 2));
if (!report.passed) process.exitCode = 1;
