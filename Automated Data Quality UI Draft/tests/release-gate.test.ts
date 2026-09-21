import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { monitoringStatusLabel, safeDisplayError } from "../lib/ui-contracts.ts";
import { scopedLink } from "../lib/client-workspace.ts";

test("Monitoring renders structured errors as text instead of React children", () => {
  assert.equal(safeDisplayError({ error_type: "connector_failure", message: "Snowflake unavailable" }), "connector failure: Snowflake unavailable");
  assert.equal(safeDisplayError({ detail: "run not found" }), "run not found");
  assert.equal(safeDisplayError({ unexpected: { nested: true } }), '{"unexpected":{"nested":true}}');
});

test("Monitoring status labels keep execution and evidence states truthful", () => {
  assert.equal(monitoringStatusLabel("FAILED"), "Failed");
  assert.equal(monitoringStatusLabel("NOT_CHECKED"), "Not checked");
  assert.equal(monitoringStatusLabel("OUTCOME_UNKNOWN"), "Outcome unknown — reconcile");
});

test("workspace navigation preserves the selected project and environment", () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", { configurable: true, value: { location: { search: "?project_id=finance%20qa&environment=test" } } });
  try {
    assert.equal(scopedLink("/monitoring?status=FAILED"), "/monitoring?status=FAILED&project_id=finance+qa&environment=test");
    assert.equal(scopedLink("/actions#execution-monitor"), "/actions?project_id=finance+qa&environment=test#execution-monitor");
  } finally {
    if (previousWindow === undefined) Reflect.deleteProperty(globalThis, "window");
    else Object.defineProperty(globalThis, "window", { configurable: true, value: previousWindow });
  }
});

test("release-gate navigation exposes task-oriented destinations", async () => {
  const shell = await readFile(new URL("../app/DraftShell.tsx", import.meta.url), "utf8");
  assert.match(shell, /label: "Ask AI"/);
  assert.match(shell, /tab=history/);
  assert.match(shell, /tab=schedules/);
  assert.match(shell, /href=\{mounted \? scopedLink\("\/register-project\?phase=overview"\)/);
  assert.match(shell, /aria-label="Open project settings"/);
});

test("execution workspace presents real keyboard-navigable tabs", async () => {
  const page = await readFile(new URL("../app/test-plan/page.tsx", import.meta.url), "utf8");
  assert.match(page, /role="tablist"/);
  assert.match(page, /role="tab" aria-selected=\{executionTab === "history"\}/);
  assert.match(page, /href=\{executionHref\("schedules"\)\}/);
});

test("project management removes repeated context copy and keeps responsive action layout", async () => {
  const shell = await readFile(new URL("../app/ProjectManagementShell.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../app/register-project/onboarding.module.css", import.meta.url), "utf8");
  assert.match(shell, /const headerDescription = contextOnly \? "" : description/);
  assert.match(css, /\.projectHeader \{ container-type: inline-size/);
  assert.match(css, /\.projectMoreActions/);
  assert.match(css, /@container \(max-width: 1060px\)/);
  assert.match(css, /\.connectionTableWrap .*container-type: inline-size/);
});

test("Phase 3 browser gate uses readiness, journeys, keyboard events, and layout assertions", async () => {
  const gate = await readFile(new URL("../scripts/release-gate-browser.mjs", import.meta.url), "utf8");
  const monitoring = await readFile(new URL("../app/monitoring/page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(gate, /sleep\(450\)/);
  assert.match(gate, /waitFor\(client/);
  assert.match(gate, /Input\.dispatchKeyEvent/);
  assert.match(gate, /Network\.setBlockedURLs/);
  assert.match(gate, /Network\.responseReceived/);
  assert.match(gate, /assetFailures/);
  assert.match(gate, /ChunkLoadError/);
  assert.match(gate, /Page\.reload/);
  assert.match(gate, /Refresh direct \/actions route/);
  assert.match(gate, /Overview current scoped state/);
  assert.match(gate, /Overview → Monitoring client navigation/);
  assert.match(gate, /Ask AI current scoped state/);
  assert.match(gate, /Refresh Ask AI route/);
  assert.match(gate, /horizontalOverflow/);
  assert.match(gate, /keyControlOverlaps/);
  assert.match(gate, /#selected-run/);
  assert.match(gate, /monitoring table filter empty state/);
  assert.match(gate, /Independent Airflow planning flow/);
  assert.match(monitoring, /load_error/);
  assert.match(monitoring, /setDetail\(value\)/);
});

test("Phase 3 API contract runner is read-only and scope-aware", async () => {
  const contracts = await readFile(new URL("../scripts/verify-phase3-contracts.mjs", import.meta.url), "utf8");
  assert.match(contracts, /api\/monitoring/);
  assert.match(contracts, /NO_MATCHING_ASSET_FILTER/);
  assert.match(contracts, /requestedProjectId/);
  assert.match(contracts, /exact detail/);
  assert.match(contracts, /Read-only API\/frontend contract verification/);
  assert.doesNotMatch(contracts, /POST|PUT|PATCH|DELETE/);
});

test("Phase 4 populated-state fixture is explicitly test-only and covers outcome states", async () => {
  const fixture = JSON.parse(await readFile(new URL("./fixtures/phase4-populated-state.json", import.meta.url), "utf8")) as {
    fixture_type?: string;
    catalog?: { assets?: unknown[] };
    lineage?: { links?: unknown[] };
    rules?: { items?: unknown[] };
    monitoring?: { states?: Array<{ status?: string }> };
  };
  assert.equal(fixture.fixture_type, "TEST_ONLY_UI_STATE");
  assert.ok((fixture.catalog?.assets?.length ?? 0) >= 3);
  assert.ok((fixture.lineage?.links?.length ?? 0) >= 2);
  assert.ok((fixture.rules?.items?.length ?? 0) >= 3);
  assert.deepEqual(new Set((fixture.monitoring?.states ?? []).map((item) => item.status)), new Set(["COMPLETED", "FAILED", "PARTIAL"]));
});

test("populated browser fixtures are explicitly gated and exercised by the release gate", async () => {
  const fixtureServer = await readFile(new URL("../lib/server-test-fixture.ts", import.meta.url), "utf8");
  const gate = await readFile(new URL("../scripts/release-gate-browser.mjs", import.meta.url), "utf8");
  assert.match(fixtureServer, /ADQ_UI_TEST_FIXTURES !== "1"/);
  assert.match(fixtureServer, /project_id.*fixture-project/);
  assert.match(fixtureServer, /TEST_ONLY_UI_FIXTURE/);
  assert.match(gate, /Populated Catalog test-only fixture/);
  assert.match(gate, /Populated Lineage test-only fixture/);
  assert.match(gate, /Populated Rules test-only fixture/);
});
