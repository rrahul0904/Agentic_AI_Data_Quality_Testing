export function currentWorkspaceParams(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  const current = new URLSearchParams(window.location.search);
  const result = new URLSearchParams();
  const projectId = current.get("project_id");
  const environment = current.get("environment");
  if (projectId) result.set("project_id", projectId);
  if (environment) result.set("environment", environment);
  return result;
}

export function scopedApiUrl(path: string): string {
  const params = currentWorkspaceParams();
  if (!params.toString()) return path;
  const [beforeHash, hash = ""] = path.split("#", 2);
  const [pathname, query = ""] = beforeHash.split("?", 2);
  const merged = new URLSearchParams(query);
  for (const [key, value] of params) if (!merged.has(key)) merged.set(key, value);
  return `${pathname}${merged.toString() ? `?${merged.toString()}` : ""}${hash ? `#${hash}` : ""}`;
}

export function scopedLink(path: string): string {
  const params = currentWorkspaceParams();
  if (!params.toString() || path.startsWith("http")) return path;
  const [beforeHash, hash = ""] = path.split("#", 2);
  const [pathname, query = ""] = beforeHash.split("?", 2);
  const merged = new URLSearchParams(query);
  for (const [key, value] of params) if (!merged.has(key)) merged.set(key, value);
  return `${pathname}${merged.toString() ? `?${merged.toString()}` : ""}${hash ? `#${hash}` : ""}`;
}
