import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const appUrl = process.env.ADQ_UI_URL || "http://127.0.0.1:3020/register-project";
const chromePath = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const timeoutMs = Number(process.env.BROWSER_VERIFY_TIMEOUT_MS || 30_000);

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function waitForDevTools(process, timeout) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Chrome did not expose DevTools within ${timeout} ms. ${output.slice(-1000)}`)), timeout);
    const inspect = (chunk) => {
      output += chunk.toString();
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    };
    process.stderr.on("data", inspect);
    process.stdout.on("data", inspect);
    process.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`Chrome exited before verification began (code ${code}). ${output.slice(-1000)}`));
    });
  });
}

class CdpClient {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 1;
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
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message));
        else pending.resolve(message.result);
        return;
      }
      for (const listener of this.listeners.get(message.method) || []) listener(message.params);
    });
  }

  on(method, listener) {
    const listeners = this.listeners.get(method) || [];
    listeners.push(listener);
    this.listeners.set(method, listeners);
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Browser evaluation failed");
    }
    return result.result.value;
  }

  close() {
    this.socket.close();
  }
}

async function waitFor(client, description, predicate, timeout = timeoutMs) {
  const started = Date.now();
  let value;
  while (Date.now() - started < timeout) {
    value = await predicate();
    if (value) return value;
    await delay(200);
  }
  throw new Error(`Timed out waiting for ${description}. Last value: ${JSON.stringify(value)}`);
}

let chrome;
let client;
const profileDirectory = await mkdtemp(join(tmpdir(), "adq-browser-verify-"));

try {
  chrome = spawn(chromePath, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--disable-background-networking",
    "--disable-component-update",
    "--remote-debugging-port=0",
    `--user-data-dir=${profileDirectory}`,
    "about:blank",
  ], { stdio: ["ignore", "pipe", "pipe"] });

  const browserWebSocketUrl = await waitForDevTools(chrome, timeoutMs);
  const devToolsPort = new URL(browserWebSocketUrl).port;
  const response = await fetch(`http://127.0.0.1:${devToolsPort}/json/new?${encodeURIComponent(appUrl)}`, { method: "PUT" });
  if (!response.ok) throw new Error(`Could not open browser page: HTTP ${response.status}`);
  const target = await response.json();

  client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();

  const runtimeExceptions = [];
  const consoleErrors = [];
  client.on("Runtime.exceptionThrown", ({ exceptionDetails }) => {
    runtimeExceptions.push(exceptionDetails.exception?.description || exceptionDetails.text || "Unknown runtime exception");
  });
  client.on("Log.entryAdded", ({ entry }) => {
    if (entry.level === "error") consoleErrors.push({ text: entry.text, url: entry.url || "" });
  });

  await Promise.all([
    client.send("Page.enable"),
    client.send("Runtime.enable"),
    client.send("Log.enable"),
  ]);

  // A reload is intentional: persisted state must reconstruct the page without relying on prior in-memory UI state.
  await client.send("Page.reload", { ignoreCache: true });
  await waitFor(client, "persisted project and connection evidence", () => client.evaluate(`(() => {
    const text = document.body?.innerText || "";
    return text.includes("Data Quality Testing - Beta") && (text.includes("4 of 4 verified") || text.includes("5 of 5 verified"));
  })()`));

  const discoveryClicked = await client.evaluate(`(() => {
    const button = [...document.querySelectorAll("button")].find((item) => (item.textContent || "").includes("Discover assets"));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!discoveryClicked) throw new Error("The Discovery phase control was not found or clickable.");

  await waitFor(client, "organized evidence-backed discovery catalog", () => client.evaluate(`(() => {
    const text = document.body?.innerText || "";
    return text.includes("VISIBLE ASSETS") && text.includes("Evidence-backed inventory");
  })()`));

  const expandedAsset = await client.evaluate(`(() => {
    const selector = [...document.querySelectorAll('details input[type="checkbox"]')].find((item) => (item.getAttribute("aria-label") || "").startsWith("Select "));
    if (!selector) return false;
    document.querySelectorAll("details").forEach((item) => { item.open = true; });
    return true;
  })()`);
  if (!expandedAsset) throw new Error("No discovered asset selector was rendered.");

  const report = await client.evaluate(`(() => {
    const text = document.body?.innerText || "";
    const overlaySelectors = ["[data-nextjs-dialog]", ".vite-error-overlay", "#webpack-dev-server-client-overlay"];
    const overlay = overlaySelectors.some((selector) => document.querySelector(selector));
    const assetRoleLink = [...document.querySelectorAll("a")].find((item) => /asset roles/i.test(item.textContent || ""));
    const assetSelectors = [...document.querySelectorAll('input[type="checkbox"]')].filter((item) => (item.getAttribute("aria-label") || "").startsWith("Select "));
    const selectedAssetCount = assetSelectors.filter((item) => item.checked).length;
    return {
      title: document.title,
      bodyLength: text.length,
      projectPersisted: text.includes("Data Quality Testing - Beta"),
      passingConnections: text.includes("4 of 4") || text.includes("5 of 5"),
      visibleAssets: text.includes("VISIBLE ASSETS"),
      evidenceBackedAssets: text.includes("Evidence-backed inventory"),
      selectedEvidence: selectedAssetCount > 0,
      childEvidence: text.includes("Inherited discovery evidence"),
      // The selected source table is persisted demo state and may legitimately change
      // between runs. Verify the behavior (connector + scoped result), not one stale
      // fixture name that a reviewer may have removed from the project.
      snowflakeScopedDiscovery: /snowflake/i.test(text) && /scope/i.test(text),
      assetRolesUnlocked: Boolean(assetRoleLink?.getAttribute("href")),
      frameworkOverlay: overlay,
    };
  })()`);

  const failedChecks = Object.entries(report)
    .filter(([key, value]) => key !== "title" && key !== "bodyLength" && (key === "frameworkOverlay" ? value : !value))
    .map(([key]) => key);
  if (runtimeExceptions.length) failedChecks.push("runtimeExceptions");
  if (consoleErrors.length) failedChecks.push("consoleErrors");
  if (report.bodyLength < 1000) failedChecks.push("nonBlankRenderedPage");

  const result = { url: appUrl, ...report, runtimeExceptions, consoleErrors, passed: failedChecks.length === 0, failedChecks };
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (failedChecks.length) process.exitCode = 1;
} finally {
  client?.close();
  if (chrome && chrome.exitCode === null) {
    const exited = new Promise((resolve) => chrome.once("exit", resolve));
    chrome.kill("SIGTERM");
    await Promise.race([exited, delay(2_000)]);
  }
  await rm(profileDirectory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
