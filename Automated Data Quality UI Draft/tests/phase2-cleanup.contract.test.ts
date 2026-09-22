import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { invalidateWorkspaceCache, readOnboardingBootstrap, rememberWorkspaceRevision, scopedApiUrl } from "../lib/client-workspace.ts";

function browser(search = "?project_id=project-alpha&environment=development") {
  const values = new Map<string, string>();
  return {
    location: { search },
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    },
  };
}

test("a cleared workspace is rendered as an explicit empty response, never a stale saved result", async () => {
  const global = globalThis as unknown as { window?: unknown };
  const previousWindow = global.window;
  global.window = browser();
  try {
    rememberWorkspaceRevision("project-alpha:development:4");
    assert.match(scopedApiUrl("/api/onboarding"), /workspace_revision=project-alpha%3Adevelopment%3A4/);

    const result = await readOnboardingBootstrap<Record<string, unknown>>(
      new Response(JSON.stringify({ bootstrapState: "EMPTY", selectedAssets: [] }), {
        headers: { "X-ADQ-Workspace-Revision": "project-alpha:development:5" },
      }),
    );
    assert.deepEqual(result, {
      kind: "empty",
      value: { bootstrapState: "EMPTY", selectedAssets: [] },
      revision: "project-alpha:development:5",
    });
    assert.match(scopedApiUrl("/api/onboarding"), /workspace_revision=project-alpha%3Adevelopment%3A5/);

    invalidateWorkspaceCache();
    assert.equal(scopedApiUrl("/api/onboarding"), "/api/onboarding?project_id=project-alpha&environment=development");
  } finally {
    global.window = previousWindow;
  }
});

test("a request failure is distinguishable from an empty scoped result", async () => {
  const result = await readOnboardingBootstrap<Record<string, unknown>>(
    new Response(JSON.stringify({ error: "State store unavailable" }), { status: 503 }),
  );
  assert.deepEqual(result, { kind: "error", error: "State store unavailable" });
});

test("cleared reconciliation and overview views cannot source current state from legacy shared browser or onboarding fallbacks", async () => {
  const root = process.cwd();
  const [reconciliationRoute, reconciliationPage, overview] = await Promise.all([
    readFile(path.join(root, "app/api/reconciliation/route.ts"), "utf8"),
    readFile(path.join(root, "app/reconciliation/page.tsx"), "utf8"),
    readFile(path.join(root, "app/page.tsx"), "utf8"),
  ]);
  assert.doesNotMatch(reconciliationRoute, /onboarding-state\.json|onboarding-connections\.json/);
  assert.match(reconciliationRoute, /discoveriesByTable/);
  assert.match(reconciliationRoute, /uniqueItems/);
  const onboardingRoute = await readFile(path.join(root, "app/api/onboarding/route.ts"), "utf8");
  assert.match(onboardingRoute, /connections\/dbt\/status/);
  assert.match(onboardingRoute, /"CONNECTED"/);
  assert.doesNotMatch(reconciliationPage, /connectionStatus\?\.source, "CONNECTED"|connectionStatus\?\.target, "CONNECTED"/);
  assert.doesNotMatch(overview, /ade-operations-summary:|ade-operations:/);
});
