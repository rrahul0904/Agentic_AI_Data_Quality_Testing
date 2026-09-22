import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Phase 3 fixture browser gate is isolated from the working project and external operations", async () => {
  const gate = await readFile(new URL("../scripts/phase3-fixture-browser-gate.mjs", import.meta.url), "utf8");
  assert.match(gate, /ADQ_UI_TEST_FIXTURES: "1"/);
  assert.match(gate, /fixture-project/);
  assert.match(gate, /fixture:\s*"phase4"/);
  assert.match(gate, /POST|PUT|PATCH|DELETE/);
  assert.match(gate, /unexpected mutation/);
  assert.match(gate, /external network request/);
  assert.doesNotMatch(gate, /data-quality-testing-beta/);
  assert.doesNotMatch(gate, /OPENAI_API_KEY|SNOWFLAKE|AIRFLOW_TOKEN/);
});

test("fixture routes expose semantic hooks used by browser checks", async () => {
  const [design, onboarding, rules] = await Promise.all([
    readFile(new URL("../app/project-design/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/register-project/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/test-plan/page.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(design, /aria-label="Interactive pipeline graph"/);
  assert.match(design, /aria-label="Search objects"/);
  assert.match(onboarding, /aria-label="Configured connections\./);
  assert.match(rules, /aria-label="Quality rules"/);
});
