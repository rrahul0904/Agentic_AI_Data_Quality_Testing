import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (path: string) => readFile(new URL(path, import.meta.url), "utf8");

test("Connections use readable labels and an accessible compact layout below the content breakpoint", async () => {
  const page = await source("../app/register-project/page.tsx");
  const css = await source("../app/register-project/onboarding.module.css");

  assert.match(page, /data-label="Connection check"/);
  assert.match(page, /connectionStatusLabel/);
  assert.match(page, /Connected/);
  assert.match(page, /role="region" aria-label="Configured connections\. Scroll to view all connection actions\."/);
  assert.match(css, /@container \(max-width: 1120px\)/);
  assert.match(css, /content: attr\(data-label\)/);
  assert.match(css, /scrollbar-gutter: stable both-edges/);
});

test("Monitoring keeps the table concise and presents run details in a keyboard-closeable dialog", async () => {
  const page = await source("../app/monitoring/page.tsx");

  assert.match(page, /<th>Job \/ asset<\/th><th>Execution<\/th><th>Verification<\/th><th>Last checked<\/th>/);
  assert.doesNotMatch(page, /<th>Submission<\/th><th>Execution<\/th><th>Verification<\/th><th>Data quality<\/th>/);
  assert.match(page, /role="dialog" aria-modal="true" aria-labelledby="selected-run-title"/);
  assert.match(page, /event\.key === "Escape"/);
  assert.match(page, /detailOpener\.current\?\.focus\(\)/);
  assert.match(page, /Open this run&apos;s evidence/);
});

test("Ask AI keeps the concise answer primary and makes evidence and technical output expandable", async () => {
  const page = await source("../app/agent/page.tsx");

  assert.match(page, /Ask about the selected project, asset, or run\. Answers cite only the scope below\./);
  assert.match(page, /<summary>Evidence and supporting records/);
  assert.match(page, /<summary>Technical details<\/summary>/);
  assert.match(page, /aria-live="polite"/);
  assert.match(page, /role="alert"/);
});

test("Lineage keeps its graph before the secondary analysis details without changing existing page logic", async () => {
  const css = await source("../app/project-design/project-design.module.css");
  assert.match(css, /\.contextFrame \.managementMain > \.analysisDetails \{ order: 8; \}/);
});
