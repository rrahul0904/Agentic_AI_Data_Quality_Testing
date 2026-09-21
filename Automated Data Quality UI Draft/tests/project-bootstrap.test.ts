import assert from "node:assert/strict";
import test from "node:test";
import { collectLocalInventory, collectProjectBootstrap, extractYamlScalar } from "../lib/project-bootstrap.ts";

const canonicalRoot = "/Users/297159/Documents/Agentic_AI/Automated Data Quality Testing";

test("extractYamlScalar reads simple project configuration", () => {
  assert.equal(extractYamlScalar("preset: tiny\nreference_date: \"2026-09-09\"\n", "preset"), "tiny");
  assert.equal(extractYamlScalar("preset: tiny\nreference_date: \"2026-09-09\"\n", "reference_date"), "2026-09-09");
});

test("local discovery counts the canonical hospitality evidence", async () => {
  const inventory = await collectLocalInventory(canonicalRoot);
  assert.deepEqual(inventory, {
    csvFiles: 34,
    parquetFiles: 30,
    jsonFiles: 1,
    totalSourceFiles: 65,
    runtimeDbtModels: 31,
    runtimeAirflowDags: 17,
    snowflakeSqlFiles: 19,
    snowpipeDefinitions: 6,
  });
});

test("bootstrap fails closed when no live API is available", async () => {
  const result = await collectProjectBootstrap({ canonicalRoot, apiCandidates: ["http://127.0.0.1:1"] });
  assert.equal(result.apiBase, null);
  assert.equal(result.execution.endToEnd, "NOT_RUN");
  assert.equal(result.connections.find((item) => item.id === "postgres")?.status, "API_OFFLINE");
  assert.equal(result.connections.find((item) => item.id === "files")?.status, "AVAILABLE");
  assert.ok(result.warnings.some((warning) => warning.includes("offline")));
});
