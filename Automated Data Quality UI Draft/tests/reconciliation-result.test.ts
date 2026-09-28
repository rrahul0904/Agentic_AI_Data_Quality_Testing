import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = () => readFile(new URL("../app/reconciliation/page.tsx", import.meta.url), "utf8");
const route = () => readFile(new URL("../app/api/reconciliation/route.ts", import.meta.url), "utf8");

test("Minus exposes key and chosen-column modes with an explicit partial-scan warning", async () => {
  const source = await page();
  assert.match(source, /All table rows by selected key/);
  assert.match(source, /Values in one chosen column/);
  assert.match(source, /comparisonBasis: "KEY"/);
  assert.match(source, /scan limit returns PARTIAL, never a full-table PASS/);
  assert.match(source, /keyComparison\.complete === false/);
});

test("quality checks do not masquerade as full source-to-target comparisons", async () => {
  const source = await page();
  assert.match(source, /const isQualityResult =/);
  assert.match(source, /isQualityResult \? <>/);
  assert.match(source, /Comparison not completed/);
  assert.match(source, /countText\(keyComparison\.missing_in_snowflake_count\)/);
  assert.doesNotMatch(source, /function number\(value: unknown\)/);
});

test("history reads scoped standalone evidence and reports fetch errors distinctly", async () => {
  const source = await route();
  const view = await page();
  assert.match(source, /x-ade-environment/);
  assert.match(source, /matchesScope\(item, "result"\)/);
  assert.match(source, /matchesScope\(item, "details"\)/);
  assert.doesNotMatch(source, /recordMatchesCurrentExecution/);
  assert.match(view, /History unavailable; retry to load saved results/);
  assert.match(view, /Comparison returned, but history could not be refreshed/);
});

test("metadata timeouts are not presented as connection configuration changes", async () => {
  const source = await route();
  const view = await page();
  assert.match(source, /METADATA_UNAVAILABLE/);
  assert.match(view, /Connector metadata unavailable/);
  assert.match(view, /"LOADING", "UNAVAILABLE"/);
});

test("reconciliation requests the bounded Snowflake table catalog, not full account inventory", async () => {
  const source = await route();
  assert.match(source, /snowflake\/metadata\?catalog_only=true/);
  assert.match(source, /snowflake\/metadata\?catalog_only=true", 16000/);
});
