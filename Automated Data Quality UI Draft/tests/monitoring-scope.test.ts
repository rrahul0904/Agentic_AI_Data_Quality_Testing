import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { clearMonitoringSelection, monitoringSelectedRunKey, monitoringScopeKey, readMonitoringFilters } from "../lib/monitoring-state.ts";

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: (key) => { values.delete(key); },
    clear: () => values.clear(),
    key: (index) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
  } as Storage;
}

test("monitoring persistence is scoped and legacy unscoped filters cannot resurrect", () => {
  const browserStorage = storage();
  const scope = { projectId: "finance qa", environment: "test" };
  browserStorage.setItem("ade-monitoring-filters", JSON.stringify({ status: "FAILED", asset: "booking_channels" }));
  assert.deepEqual(readMonitoringFilters(browserStorage, scope), { status: "", technology: "", asset: "", since: "", until: "", page: 1 });
  browserStorage.setItem(`ade-monitoring-filters:${monitoringScopeKey(scope)}`, JSON.stringify({ status: "FAILED", asset: "properties", page: 2 }));
  assert.deepEqual(readMonitoringFilters(browserStorage, scope), { status: "FAILED", technology: "", asset: "properties", since: "", until: "", page: 2 });
});

test("changing or clearing monitoring scope removes both current and pre-scope selected runs", () => {
  const browserStorage = storage();
  const scope = { projectId: "finance qa", environment: "test" };
  browserStorage.setItem(monitoringSelectedRunKey(scope), "run-current");
  browserStorage.setItem("ade-monitoring-selected-run:finance qa:test", "run-old-tab");
  clearMonitoringSelection(browserStorage, scope);
  assert.equal(browserStorage.getItem(monitoringSelectedRunKey(scope)), null);
  assert.equal(browserStorage.getItem("ade-monitoring-selected-run:finance qa:test"), null);
});

test("monitoring and overview present persisted records as historical and keep Airflow on its configured endpoint", async () => {
  const [monitoring, overview, shell] = await Promise.all([
    readFile(new URL("../app/monitoring/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/DraftShell.tsx", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(monitoring, /data-quality-testing-beta|persisted\.projectId|persisted\.environment/);
  assert.match(monitoring, /PERSISTED JOBS/);
  assert.match(monitoring, /No persisted jobs for this project and environment/);
  assert.match(overview, /Persisted history is not presented as current state/);
  assert.match(overview, /Airflow uses its configured runtime endpoint/);
  assert.match(overview, /integrationEndpoint\(value\)/);
  assert.match(shell, /scopedApiUrl\("\/api\/workspace"\)/);
});
