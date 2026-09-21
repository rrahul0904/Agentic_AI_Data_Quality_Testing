import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixturePath = path.join(root, "tests", "fixtures", "phase4-populated-state.json");
const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
const failures = [];
const fail = (message) => failures.push(message);
const isObject = (value) => value && typeof value === "object" && !Array.isArray(value);

if (fixture.fixture_type !== "TEST_ONLY_UI_STATE") fail("fixture must be explicitly marked test-only");
for (const key of ["project_id", "environment", "discovery_snapshot_id", "plan_id", "run_id"]) {
  if (!fixture.scope?.[key]) fail(`scope.${key} is required`);
}
for (const section of ["catalog", "lineage", "rules", "monitoring"]) {
  if (!isObject(fixture[section])) fail(`${section} section is required`);
  if (fixture[section]?.status !== "PASS") fail(`${section}.status must be PASS for the populated fixture`);
}

const assets = Array.isArray(fixture.catalog?.assets) ? fixture.catalog.assets : [];
const links = Array.isArray(fixture.lineage?.links) ? fixture.lineage.links : [];
const rules = Array.isArray(fixture.rules?.items) ? fixture.rules.items : [];
const runs = Array.isArray(fixture.monitoring?.states) ? fixture.monitoring.states : [];
if (assets.length < 3) fail("catalog must contain source, transformation, and target assets");
if (links.length < 2) fail("lineage must contain at least two links");
if (rules.length < 3) fail("rules must contain multiple approval/result states");
if (runs.length < 3) fail("monitoring must contain success, failure, and partial states");

const assetIds = new Set(assets.map((item) => item.id));
if (assetIds.size !== assets.length) fail("catalog asset IDs must be unique");
for (const link of links) {
  if (!link.id || !assetIds.has(link.source) || !assetIds.has(link.target)) fail(`lineage link ${link.id || "unknown"} has an invalid asset reference`);
}
const runIds = new Set(runs.map((item) => item.run_id));
if (runIds.size !== runs.length) fail("monitoring run IDs must be unique");
const statuses = new Set(runs.map((item) => item.status));
for (const expected of ["COMPLETED", "FAILED", "PARTIAL"]) {
  if (!statuses.has(expected)) fail(`monitoring is missing ${expected} coverage`);
}
for (const rule of rules) {
  if (!rule.id || !assetIds.has(rule.asset_id)) fail(`rule ${rule.id || "unknown"} has an invalid asset reference`);
  if (!["PASS", "FAIL", "NOT_CHECKED"].includes(rule.latest_result)) fail(`rule ${rule.id || "unknown"} has an invalid result state`);
}

if (failures.length) {
  console.error(JSON.stringify({ fixture: fixturePath, failures }, null, 2));
  process.exit(1);
}
console.log(JSON.stringify({ fixture: fixturePath, fixture_id: fixture.fixture_id, catalog_assets: assets.length, lineage_links: links.length, rules: rules.length, monitoring_states: runs.length, status: "PASS" }, null, 2));
