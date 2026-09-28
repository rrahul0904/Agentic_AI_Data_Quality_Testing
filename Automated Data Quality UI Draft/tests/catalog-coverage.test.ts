import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  acceptedAssetCount,
  analyzedFlowCount,
  catalogAvailability,
  runtimeEvidenceCounts,
  sourceTableDiscoveryCoverage,
  uniqueSourceTables,
} from "../lib/catalog-coverage.ts";
import { liveCatalogTableCount, onboardedTableCount, runtimeIncorporationNote } from "../lib/project-scope-contract.ts";

const table = (id: string, schema = "public", name = "guests") => ({
  id,
  database: "hospitality_oltp",
  schema,
  table: name,
  columns: [],
});

test("saved source table count handles empty, one, and many selections", () => {
  assert.equal(uniqueSourceTables([]).length, 0);
  assert.equal(uniqueSourceTables([table("guests")]).length, 1);
  assert.equal(uniqueSourceTables(Array.from({ length: 15 }, (_, index) => table(`table-${index}`, "public", `table_${index}`))).length, 15);
  assert.equal(onboardedTableCount([]), 0);
  assert.equal(onboardedTableCount([table("guests")]), 1);
  assert.equal(onboardedTableCount(Array.from({ length: 15 }, (_, index) => table(`table-${index}`, "public", `table_${index}`))), 15);
});

test("source tables deduplicate canonical identities without conflating schemas", () => {
  const result = uniqueSourceTables([table("old-id"), table("new-id", "PUBLIC", "GUESTS"), table("other", "archive", "guests")]);
  assert.equal(result.length, 2);
  assert.deepEqual(result.map((item) => item.id), ["old-id", "other"]);
});

test("catalog unavailable or cached never appears as a live zero", () => {
  const entries = [{ database: "db", schema: "public", table: "guests" }];
  assert.deepEqual(catalogAvailability(entries, "CONNECTED"), { state: "AVAILABLE", availableCount: 1, cachedCount: 0 });
  assert.deepEqual(catalogAvailability(entries, "CACHED DISCOVERY"), { state: "CACHED", availableCount: null, cachedCount: 1 });
  assert.deepEqual(catalogAvailability([], "UNAVAILABLE"), { state: "UNAVAILABLE", availableCount: null, cachedCount: 0 });
  assert.equal(catalogAvailability([], "METADATA_UNAVAILABLE").state, "UNAVAILABLE");
  assert.equal(catalogAvailability([], "LOADING").availableCount, null);
  assert.equal(catalogAvailability([], "CONFIGURATION CHANGED").availableCount, null);
  assert.equal(catalogAvailability([], "CONNECTED").availableCount, 0);
  assert.equal(liveCatalogTableCount("CONNECTED", 15), 15);
  assert.equal(liveCatalogTableCount("UNAVAILABLE", 15), null);
});

test("accepted analysis assets deduplicate repeated identities but retain distinct namespaces", () => {
  const nodes = [
    { node_id: "asset-a", kind: "source_table", name: "guests", properties: { connection_kind: "postgres", catalog: "hospitality_oltp", schema: "public" } },
    { node_id: "asset-b", kind: "source_table", name: "GUESTS", properties: { connection_kind: "POSTGRES", catalog: "HOSPITALITY_OLTP", schema: "PUBLIC" } },
    { node_id: "asset-c", kind: "source_table", name: "guests", properties: { connection_kind: "postgres", catalog: "hospitality_oltp", schema: "archive" } },
    { node_id: "asset-d", kind: "warehouse_table", name: "guests", properties: { connection_kind: "snowflake", catalog: "hospitality_oltp", schema: "public" } },
  ];
  assert.equal(acceptedAssetCount(nodes), 3);
});

test("analyzed flows deduplicate IDs and ignore empty entries", () => {
  assert.equal(analyzedFlowCount(["flow-a", "FLOW-A", "flow-b", "", null]), 2);
  assert.equal(analyzedFlowCount([]), 0);
});

test("runtime evidence is zero only as a count and remains unrefreshed without timestamp", () => {
  assert.deepEqual(runtimeEvidenceCounts(undefined), { nodes: 0, edges: 0, refreshedAt: null });
  assert.deepEqual(runtimeEvidenceCounts({ observed_node_count: 4.8, observed_edge_count: -2, refreshed_at: "2026-09-23T10:00:00Z" }), { nodes: 4, edges: 0, refreshedAt: "2026-09-23T10:00:00Z" });
});

test("same-named source and target remain different identities, and connector outage preserves onboarded scope", () => {
  const source = table("postgres-guests", "public", "guests");
  const target = { id: "snowflake-guests", database: "HOSPITALITY_RELIABILITY_LAB", schema: "RAW", table: "GUESTS", columns: [] };
  assert.equal(uniqueSourceTables([source, target]).length, 2);
  assert.equal(liveCatalogTableCount("UNAVAILABLE", null), null);
  assert.equal(onboardedTableCount([source]), 1);
});

test("runtime note distinguishes an out-of-date analysis and unbound project runs without guessing table scope", () => {
  assert.match(runtimeIncorporationNote({ latestRunAt: "2026-09-23T11:00:00Z", refreshedAt: "2026-09-23T10:00:00Z" }), /not been refreshed since it/);
  assert.match(runtimeIncorporationNote({ latestRunAt: "2026-09-23T10:00:00Z", refreshedAt: "2026-09-23T11:00:00Z", observedEdges: 0 }), /no exact adapter-observed lineage edge/);
  const latestAction = "action_run_48474abe75d941e484a50d31c642f873";
  assert.match(`A project/environment action run exists (${latestAction}), but its plan has no binding to the active source table.`, /no binding to the active source table/);
});

test("discovery coverage denominator deduplicates selected tables", () => {
  const selected = [table("first-id"), table("duplicate-id", "PUBLIC", "GUESTS"), table("stays", "public", "stays")];
  const nodes = [{ node_id: "source-guests", kind: "source_table", name: "postgres.public.guests", properties: { source_table_id: "first-id" } }];
  const coverage = sourceTableDiscoveryCoverage(selected, nodes);
  assert.equal(coverage.discovered, 1);
  assert.equal(coverage.missing.length, 1);
  assert.equal(coverage.missing[0].table, "stays");
});

test("onboarding and analysis label live, saved, accepted, flow, and runtime counts separately", async () => {
  const onboarding = await readFile(new URL("../app/register-project/page.tsx", import.meta.url), "utf8");
  const analysis = await readFile(new URL("../app/project-design/page.tsx", import.meta.url), "utf8");
  assert.match(onboarding, /Available PostgreSQL tables/);
  assert.match(onboarding, /Snowflake target catalog entries/);
  assert.match(onboarding, /Selected \/ onboarded source tables/);
  assert.match(onboarding, /Assets in active table discovery/);
  assert.match(onboarding, /Live PostgreSQL metadata unavailable/);
  assert.match(analysis, /Available Snowflake catalog entries/);
  assert.match(analysis, /Accepted analysis assets/);
  assert.match(analysis, /Analyzed flows/);
  assert.match(analysis, /Runtime-verified evidence/);
  assert.match(analysis, /live count not confirmed/);
});

test("one shared project-scope summary is rendered across all DraftShell-backed pages", async () => {
  const [shell, route, workspace, onboarding, monitoring] = await Promise.all([
    readFile(new URL("../app/DraftShell.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/project-scope/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/server-workspace.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/register-project/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/monitoring/page.tsx", import.meta.url), "utf8"),
  ]);
  for (const label of ["Live source tables", "Onboarded tables", "Accepted assets", "Source-rooted flows", "Runtime verified"]) assert.match(shell, new RegExp(label));
  assert.match(shell, /\/api\/project-scope/);
  assert.match(route, /projectWorkflowSnapshot\(workspace\)/);
  assert.match(route, /extensions\.tables/);
  assert.match(route, /analysis_scope_current/);
  assert.match(route, /no binding to the active source table/);
  assert.match(route, /not attributed by name/);
  assert.match(workspace, /projectWorkflowSnapshot/);
  assert.match(shell, /addEventListener\("popstate"/);
  assert.match(onboarding, /notifyProjectScopeChanged\(\)/);
  assert.match(monitoring, /dispatchEvent\(new Event\("ade-workspace-scope-change"\)\)/);
});
