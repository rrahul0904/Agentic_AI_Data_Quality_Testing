"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { OnboardingBootstrap } from "../lib/onboarding";
import DraftShell from "./DraftShell";
import styles from "./workflow.module.css";
import local from "./project-management-shell.module.css";
import { scopedApiUrl, scopedLink } from "../lib/client-workspace";
import { ProjectSelector } from "./components/ui";

export type ManagementPhase = "overview" | "definition" | "connections" | "discovery" | "objects" | "map" | "rules" | "review";

type Props = {
  phase: ManagementPhase;
  title: string;
  description: string;
  headerActions?: ReactNode;
  navActive?: "register" | "design" | "map" | "plan";
  contextOnly?: boolean;
  children: ReactNode;
};

const phases: Array<{ id: ManagementPhase; title: string; detail: string; href: string }> = [
  { id: "definition", title: "Define project", detail: "Business boundary", href: "/register-project?phase=definition" },
  { id: "connections", title: "Connect systems", detail: "Configure and test", href: "/register-project?phase=connections" },
  { id: "discovery", title: "Discover assets", detail: "Run and select", href: "/register-project?phase=discovery" },
  { id: "map", title: "Lineage", detail: "Evidence graph", href: "/map-flows" },
  { id: "rules", title: "Define quality rules", detail: "Deterministic checks", href: "/test-plan?view=contracts&mode=review" },
  { id: "review", title: "Review and run", detail: "Approve and execute", href: "/test-plan?view=execution&mode=review" },
];

function displayEnvironment(value?: string): string {
  if (!value) return "Not set";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function ProjectManagementShell({ phase, title, description, headerActions, navActive, contextOnly = false, children }: Props) {
  const [bootstrap, setBootstrap] = useState<OnboardingBootstrap | null>(null);
  const [planStatus, setPlanStatus] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let mounted = true;
    setHydrated(true);
    void fetch(scopedApiUrl("/api/onboarding"), { cache: "no-store" }).then((response) => response.ok ? response.json() as Promise<OnboardingBootstrap> : Promise.reject(new Error("onboarding unavailable"))).then((value) => { if (mounted) setBootstrap(value); }).catch(() => { /* page content remains usable if bootstrap is unavailable */ });
    void fetch(scopedApiUrl("/api/quality-plans"), { cache: "no-store", signal: AbortSignal.timeout(8000) }).then((response) => response.ok ? response.json() as Promise<{ plan?: { status?: string } | null }> : Promise.reject(new Error("plan unavailable"))).then((value) => { if (mounted) setPlanStatus(value.plan?.status ?? null); }).catch(() => { if (mounted) setPlanStatus(null); });
    return () => { mounted = false; };
  }, []);

  const definition = bootstrap?.projectDefinition ?? {};
  const projectName = String(definition.name || bootstrap?.project.name || "Data Quality Project");
  const environment = displayEnvironment(String(definition.environment || bootstrap?.project.environment || ""));
  const owner = String(definition.owner || "Not assigned");
  const passed = Object.values(bootstrap?.savedTests ?? {}).filter((item) => item.status === "PASS").length;
  const connections = bootstrap?.savedConnections ?? [];
  const discoveryRuns = Object.keys(bootstrap?.savedDiscoveries ?? {}).length;
  const discoveryReady = connections.length > 0 && connections.every((item) => bootstrap?.savedTests[item.id]?.status === "PASS" && bootstrap?.savedDiscoveries[item.id]?.status === "PASS");
  const mappingReady = discoveryReady && (bootstrap?.selectedAssets?.length ?? 0) > 0 && Boolean(bootstrap?.analysisScopeId && bootstrap?.analysisScopeId === bootstrap?.sourceTableScopeId);
  const qualityPlanReady = mappingReady && Boolean(bootstrap?.qualityPlanScopeId && bootstrap?.qualityPlanScopeId === bootstrap?.sourceTableScopeId) && Boolean(planStatus && !["NOT_GENERATED", "NOT_RUN"].includes(planStatus.toUpperCase()));
  const phaseComplete = useMemo(() => [Boolean(String(definition.name || "").trim() && String(definition.owner || "").trim()), connections.length > 0 && passed === connections.length, discoveryReady, mappingReady, qualityPlanReady, false].map(Boolean), [connections.length, definition.name, definition.owner, discoveryReady, mappingReady, passed, planStatus, qualityPlanReady]);
  const reviewLockReason = qualityPlanReady ? "No verified execution evidence exists yet. Approve and run the quality plan to complete this phase." : "Define and review at least one quality rule before review and run.";
  const lockReason: Partial<Record<ManagementPhase, string>> = {
    map: "Requires every connection to pass testing and return discovery evidence.",
    rules: "Requires completed evidence-backed mapping for the selected assets.",
    review: reviewLockReason,
  };
  const available: Partial<Record<ManagementPhase, boolean>> = { map: discoveryReady, rules: mappingReady, review: qualityPlanReady };
  const lock = !contextOnly && lockReason[phase] && !available[phase] ? { reason: lockReason[phase]!, href: phase === "map" ? phases[2].href : phase === "rules" ? phases[3].href : phases[4].href } : null;

  const scopedHref = (href: string) => {
    // Keep the first client render identical to the server render.  The
    // workspace query is browser-derived, so adding it during SSR would make
    // Next.js hydrate a different href than the one it initially rendered.
    if (!hydrated) return href;
    const projectId = bootstrap?.currentProjectId;
    if (!projectId) return scopedLink(href);
    const [pathname, search = ""] = href.split("?");
    const params = new URLSearchParams(search);
    if (!params.has("project_id")) params.set("project_id", projectId);
    return `${pathname}?${params.toString()}`;
  };

  const switchProject = (id: string) => { window.location.assign(`/register-project?project_id=${encodeURIComponent(id)}&phase=overview`); };
  const newProject = () => { window.location.assign("/register-project?new=1"); };
  const saveAsNew = () => { window.location.assign("/register-project?saveAs=1"); };
  const saveChanges = () => { window.location.assign("/register-project?phase=definition"); };

  const shellActive = contextOnly ? (phase === "review" ? "plan" : navActive ?? "register") : navActive ?? "register";
  const shellPlanView = contextOnly && shellActive === "plan" ? (phase === "review" ? "execution" : "contracts") : undefined;
  // Context pages already show project/environment in the metadata row. Keep
  // their header focused on the task instead of repeating governance copy.
  const headerDescription = contextOnly ? "" : description;
  return <DraftShell active={shellActive} planView={shellPlanView}>
    <div className={local.managementPage}>
      <header className={`${styles.topbar} ${contextOnly ? styles.topbarContext : ""}`}>
        <div><span className={styles.eyebrow}>{contextOnly ? title.toUpperCase() : "PROJECT MANAGEMENT"}</span><h1>{contextOnly ? title : projectName}</h1>{headerDescription && <p>{headerDescription}</p>}<div className={local.projectMeta}><span>Project <strong>{projectName}</strong></span><span>Environment <strong>{environment}</strong></span><span>Owner <strong>{owner}</strong></span><span>{bootstrap?.projectSavedAt ? `Last saved ${new Date(bootstrap.projectSavedAt).toLocaleString()}` : "Not saved yet"}</span></div></div>
        <div className={styles.topActions}><ProjectSelector projects={(bootstrap?.projects ?? []).map((item) => ({ id: item.id, name: String(item.projectDefinition.name || "New project") }))} currentProjectId={bootstrap?.currentProjectId ?? ""} onChange={switchProject} />{!contextOnly && <><button className={styles.secondary} onClick={newProject}>Start new project</button><button className={styles.quiet} onClick={saveAsNew}>Save as new</button><button className={styles.primary} onClick={saveChanges} title="Open Define project to save project changes">Save changes</button></>}{headerActions}</div>
      </header>
      <div className={`${local.managementFrame} ${contextOnly ? local.contextFrame : ""}`}>
        {!contextOnly && <aside className={local.managementNav}>
          <>
          <Link className={`${local.lifecycleItem} ${phase === "overview" ? local.lifecycleItemActive : ""}`} href={scopedHref("/register-project")}><span className={local.lifecycleNumber}>⌂</span><span className={local.lifecycleCopy}><strong>Overview</strong><small>Project health and next action</small></span></Link>
          <div className={local.navSectionLabel}>PROJECT LIFECYCLE</div>
          {phases.map((item, index) => {
            const isLocked = Boolean(lockReason[item.id] && !available[item.id]);
            const itemClass = `${local.lifecycleItem} ${phase === item.id ? local.lifecycleItemActive : ""} ${phaseComplete[index] ? local.lifecycleItemComplete : ""} ${isLocked ? local.lifecycleItemLocked : ""}`;
            const detail = isLocked ? lockReason[item.id] : phaseComplete[index] ? "Complete" : item.detail;
            const body = <><span className={local.lifecycleNumber}>{phaseComplete[index] ? "✓" : index + 1}</span><span className={local.lifecycleCopy}><strong>{item.title}</strong><small>{detail}</small></span></>;
            return isLocked ? <div className={itemClass} title={lockReason[item.id]} key={item.id}>{body}</div> : <Link className={itemClass} href={scopedHref(item.href)} key={item.id}>{body}</Link>;
          })}
          </>
        </aside>}
        <main className={local.managementMain}>
          {!contextOnly && <div className={local.pageIntro}><div><span className={styles.eyebrow}>{title.toUpperCase()}</span><h2>{title}</h2><p>{description}</p></div></div>}
          {lock && <div className={local.lockBanner} role="status"><div><strong>{title} is locked.</strong><span>{lock.reason}</span></div><Link className={`${styles.secondary} ${local.headerLink}`} href={lock.href}>Go to prerequisite →</Link></div>}
          {children}
        </main>
      </div>
    </div>
  </DraftShell>;
}
