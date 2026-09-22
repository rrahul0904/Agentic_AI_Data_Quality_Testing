export function currentWorkspaceParams(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  const current = new URLSearchParams(window.location.search);
  const result = new URLSearchParams();
  const projectId = current.get("project_id");
  const environment = current.get("environment");
  const fixture = current.get("fixture");
  if (projectId) result.set("project_id", projectId);
  if (environment) result.set("environment", environment);
  if (fixture) result.set("fixture", fixture);
  return result;
}

type WorkspaceScopeParts = { projectId: string; environment: string };

export type OnboardingBootstrapResult<T> =
  | { kind: "saved"; value: T; revision?: string }
  | { kind: "empty"; value: T; revision?: string }
  | { kind: "error"; error: string; revision?: string };

const REVISION_STORAGE_PREFIX = "ade-workspace-revision:";

function scopeParts(params: URLSearchParams): WorkspaceScopeParts {
  return {
    projectId: params.get("project_id") || "default",
    environment: params.get("environment") || "default",
  };
}

export function workspaceCacheKey(parts: WorkspaceScopeParts): string {
  return `${parts.projectId}:${parts.environment}`;
}

export function workspaceRevisionStorageKey(parts: WorkspaceScopeParts): string {
  return `${REVISION_STORAGE_PREFIX}${workspaceCacheKey(parts)}`;
}

function sessionStorageForBrowser(): Storage | null {
  if (typeof window === "undefined") return null;
  try { return window.sessionStorage; }
  catch { return null; }
}

function validRevision(revision: unknown): revision is string {
  return typeof revision === "string" && /^[a-z0-9-]+:[a-z0-9_-]+:\d+$/i.test(revision);
}

/** Store the revision received from an onboarding response.  The revision is
 * kept per project/environment, so switching workspaces cannot invalidate or
 * reuse another project's client cache key. */
export function rememberWorkspaceRevision(revision: unknown, params = currentWorkspaceParams()): void {
  if (!validRevision(revision)) return;
  const storage = sessionStorageForBrowser();
  if (!storage) return;
  try { storage.setItem(workspaceRevisionStorageKey(scopeParts(params)), revision); }
  catch { /* Private-mode storage can be unavailable; no-store still applies. */ }
}

/** Forget a workspace revision after the UI has cleared its active scope. */
export function invalidateWorkspaceCache(params = currentWorkspaceParams()): void {
  const storage = sessionStorageForBrowser();
  if (!storage) return;
  try { storage.removeItem(workspaceRevisionStorageKey(scopeParts(params))); }
  catch { /* Storage is optional. */ }
}

function storedWorkspaceRevision(params: URLSearchParams): string {
  const storage = sessionStorageForBrowser();
  const expectedScope = scopeParts(params);
  const revisionProject = expectedScope.projectId
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "data-quality-project";
  const revisionEnvironment = expectedScope.environment.trim().toLowerCase() || "development";
  const belongsToScope = (revision: string): boolean => {
    if (expectedScope.projectId === "default" && expectedScope.environment === "default") return true;
    return revision.startsWith(`${revisionProject}:${revisionEnvironment}:`);
  };
  try {
    const revision = storage?.getItem(workspaceRevisionStorageKey(expectedScope));
    if (validRevision(revision) && belongsToScope(revision)) return revision;
  } catch { /* Fall through to the server-issued cookie. */ }
  if (typeof document === "undefined") return "";
  const cookie = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith("ade-workspace-revision="));
  const revision = cookie ? decodeURIComponent(cookie.slice("ade-workspace-revision=".length)) : "";
  return validRevision(revision) && belongsToScope(revision) ? revision : "";
}

function cacheBustedParams(params: URLSearchParams): URLSearchParams {
  const result = new URLSearchParams(params);
  const revision = storedWorkspaceRevision(result);
  if (revision && !result.has("workspace_revision")) result.set("workspace_revision", revision);
  return result;
}

/**
 * Classifies a bootstrap response without treating a valid empty workspace as
 * a transport failure. It also remembers the server-issued revision so later
 * scoped requests receive a distinct URL after a scope clear.
 */
export async function readOnboardingBootstrap<T extends Record<string, unknown>>(
  response: Response,
  params = currentWorkspaceParams(),
): Promise<OnboardingBootstrapResult<T>> {
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  const revision = response.headers.get("X-ADQ-Workspace-Revision") || payload.workspaceRevision;
  if (response.ok) {
    rememberWorkspaceRevision(revision, params);
    const kind = payload.bootstrapState === "EMPTY" ? "empty" : "saved";
    return { kind, value: payload as T, ...(validRevision(revision) ? { revision } : {}) };
  }
  const error = typeof payload.error === "string" && payload.error ? payload.error : `Onboarding request failed (${response.status})`;
  return { kind: "error", error, ...(validRevision(revision) ? { revision } : {}) };
}

export function scopedApiUrl(path: string): string {
  const params = cacheBustedParams(currentWorkspaceParams());
  if (!params.toString()) return path;
  const [beforeHash, hash = ""] = path.split("#", 2);
  const [pathname, query = ""] = beforeHash.split("?", 2);
  const merged = new URLSearchParams(query);
  for (const [key, value] of params) if (!merged.has(key)) merged.set(key, value);
  return `${pathname}${merged.toString() ? `?${merged.toString()}` : ""}${hash ? `#${hash}` : ""}`;
}

export function scopedLink(path: string): string {
  const params = cacheBustedParams(currentWorkspaceParams());
  if (!params.toString() || path.startsWith("http")) return path;
  const [beforeHash, hash = ""] = path.split("#", 2);
  const [pathname, query = ""] = beforeHash.split("?", 2);
  const merged = new URLSearchParams(query);
  for (const [key, value] of params) if (!merged.has(key)) merged.set(key, value);
  return `${pathname}${merged.toString() ? `?${merged.toString()}` : ""}${hash ? `#${hash}` : ""}`;
}

/** Ensure the browser URL carries the same explicit scope returned by the server. */
export function normalizeWorkspaceUrl(scope: { projectId?: unknown; environment?: unknown }): void {
  if (typeof window === "undefined") return;
  const projectId = typeof scope.projectId === "string" ? scope.projectId.trim() : "";
  const environment = typeof scope.environment === "string" ? scope.environment.trim().toLowerCase() : "";
  if (!projectId || !environment) return;
  const url = new URL(window.location.href);
  let changed = false;
  if (url.searchParams.get("project_id") !== projectId) {
    url.searchParams.set("project_id", projectId);
    changed = true;
  }
  if (url.searchParams.get("environment") !== environment) {
    url.searchParams.set("environment", environment);
    changed = true;
  }
  if (changed) {
    window.history.replaceState(window.history.state, "", url.toString());
    window.dispatchEvent(new Event("ade-workspace-scope-change"));
  }
}
