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
  assert.match(css, /\.projectActions \{ display: grid; grid-template-columns: minmax\(250px, 1\.4fr\) repeat\(4, minmax\(118px, 1fr\)\)/);
  assert.match(css, /@media \(max-width: 1260px\)/);
});
