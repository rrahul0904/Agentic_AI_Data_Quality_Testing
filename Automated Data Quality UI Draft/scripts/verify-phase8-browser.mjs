import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Dependency-free browser contract check. It is read-only and submits no
// connector, pipeline, or quality operation.
const base = process.env.ADQ_UI_URL || "http://127.0.0.1:3020";
const chromePath = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const timeoutMs = Number(process.env.BROWSER_VERIFY_TIMEOUT_MS || 30_000);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function devtools(proc) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Chrome DevTools timeout: ${output.slice(-500)}`)), timeoutMs);
    const read = (chunk) => { output += chunk.toString(); const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/); if (match) { clearTimeout(timer); resolve(match[1]); } };
    proc.stderr.on("data", read); proc.stdout.on("data", read);
    proc.once("exit", (code) => { clearTimeout(timer); reject(new Error(`Chrome exited (${code})`)); });
  });
}
class Cdp {
  constructor(url) { this.socket = new WebSocket(url); this.id = 0; this.pending = new Map(); }
  async connect() { await new Promise((resolve, reject) => { this.socket.addEventListener("open", resolve, { once: true }); this.socket.addEventListener("error", reject, { once: true }); }); this.socket.addEventListener("message", async (event) => { const message = JSON.parse(typeof event.data === "string" ? event.data : await event.data.text()); const pending = this.pending.get(message.id); if (!pending) return; this.pending.delete(message.id); message.error ? pending.reject(new Error(message.error.message)) : pending.resolve(message.result); }); }
  send(method, params = {}) { const id = ++this.id; return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.socket.send(JSON.stringify({ id, method, params })); }); }
  async eval(expression) { const result = await this.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "browser evaluation failed"); return result.result.value; }
  close() { this.socket.close(); }
}
const profile = await mkdtemp(join(tmpdir(), "adq-phase8-browser-"));
let chrome; let client;
try {
  chrome = spawn(chromePath, ["--headless=new", "--disable-gpu", "--no-first-run", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "pipe", "pipe"] });
  const ws = await devtools(chrome); const port = new URL(ws).port;
  const opened = await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(`${base}/monitoring?project_id=data-quality-testing-beta&environment=development`)}`, { method: "PUT" });
  if (!opened.ok) throw new Error(`cannot open monitoring page (${opened.status})`);
  const target = await opened.json(); client = new Cdp(target.webSocketDebuggerUrl); await client.connect(); await client.send("Runtime.enable"); await client.send("Page.enable"); await sleep(500);
  const monitoring = await client.eval(`document.body?.innerText || ""`);
  if (!/monitoring|execution|run/i.test(monitoring)) throw new Error("monitoring status surface did not render");
  await client.send("Page.navigate", { url: `${base}/actions?project_id=data-quality-testing-beta#execution-monitor` }); await sleep(500);
  const actions = await client.eval(`document.body?.innerText || ""`);
  const interruptedRequest = await client.eval(`(async () => { const controller = new AbortController(); const request = fetch('/api/monitoring?project_id=data-quality-testing-beta', { signal: controller.signal }).catch(error => error.name); controller.abort(); return await request; })()`);
  const report = { exactRunNavigation: /execution|run|plan/i.test(actions), scopeControl: await client.eval(`Boolean(document.querySelector('select, [role="combobox"], input[aria-label*="project" i]'))`), statusPresentation: /pending|not run|monitoring|completed|failed|awaiting/i.test(actions), interruptedRequest: interruptedRequest === "AbortError" };
  report.passed = report.exactRunNavigation && report.scopeControl && report.statusPresentation && report.interruptedRequest;
  console.log(JSON.stringify(report)); if (!report.passed) process.exitCode = 1;
} finally { client?.close(); if (chrome && chrome.exitCode === null) chrome.kill("SIGTERM"); await rm(profile, { recursive: true, force: true, maxRetries: 3 }); }
