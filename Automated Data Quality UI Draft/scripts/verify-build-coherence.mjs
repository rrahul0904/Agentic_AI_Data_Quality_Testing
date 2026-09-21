import { access, readFile } from "node:fs/promises";
import { constants } from "node:fs";
import { join, resolve } from "node:path";

const uiRoot = resolve(process.env.ADQ_UI_ROOT || process.cwd());
const base = (process.env.ADQ_UI_URL || "http://127.0.0.1:3020").replace(/\/$/, "");
const buildDir = process.env.ADQ_BUILD_DIR || ".next-production";
const output = { ui_root: uiRoot, url: base, build_dir: buildDir, passed: false, checks: [], assets: [], failures: [] };

async function exists(path) {
  try { await access(path, constants.F_OK); return true; } catch { return false; }
}
function check(name, passed, details = {}) {
  output.checks.push({ name, passed, ...details });
  if (!passed) output.failures.push({ name, ...details });
}

async function main() {
  const buildRoot = join(uiRoot, buildDir);
  const buildIdPath = join(buildRoot, "BUILD_ID");
  const buildId = await exists(buildIdPath) ? (await readFile(buildIdPath, "utf8")).trim() : null;
  check("production_build_id", Boolean(buildId), { path: buildIdPath, build_id: buildId });
  for (const name of ["build-manifest.json", "app-build-manifest.json"]) {
    const path = join(buildRoot, name);
    check(name, await exists(path), { path });
  }

  let html = "";
  try {
    const response = await fetch(`${base}/`, { headers: { accept: "text/html" }, signal: AbortSignal.timeout(10000) });
    html = await response.text();
    check("root_document", response.ok, { status: response.status, content_type: response.headers.get("content-type") });
    check("root_document_is_html", (response.headers.get("content-type") || "").includes("text/html"), { status: response.status });
  } catch (error) {
    check("root_document", false, { error: error instanceof Error ? error.message : String(error) });
  }

  const assets = [...new Set([...html.matchAll(/(?:src|href)=["'](\/_next\/static\/[^"']+\.(?:js|css)(?:\?[^"']*)?)["']/g)].map((match) => match[1]))];
  check("root_references_built_assets", assets.length > 0, { asset_count: assets.length });
  for (const asset of assets) {
    try {
      const response = await fetch(`${base}${asset}`, { signal: AbortSignal.timeout(10000) });
      const item = { asset, status: response.status, content_type: response.headers.get("content-type") };
      output.assets.push(item);
      check(`asset:${asset}`, response.ok, item);
      if (asset.endsWith(".js") || asset.includes(".js?")) check(`asset_content_type:${asset}`, (item.content_type || "").includes("javascript"), item);
    } catch (error) {
      const item = { asset, error: error instanceof Error ? error.message : String(error) };
      output.assets.push(item);
      check(`asset:${asset}`, false, item);
    }
  }
  output.passed = output.failures.length === 0;
  console.log(JSON.stringify({ ...output, generated_at: new Date().toISOString() }, null, 2));
  if (!output.passed) process.exitCode = 1;
}
await main();
