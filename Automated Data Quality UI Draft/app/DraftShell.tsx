"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import styles from "./workflow.module.css";
import { scopedLink } from "../lib/client-workspace";

type DraftShellProps = {
  active: "operations" | "register" | "plan" | "design" | "map" | "reconciliation" | "monitoring" | "actions" | "incidents" | "investigations" | "agent";
  planView?: "contracts" | "execution";
  children: ReactNode;
};

type NavKey = DraftShellProps["active"];
type NavItem = { label: string; icon: string; href: string; active: NavKey; planView?: DraftShellProps["planView"]; setting?: "project" | "connections" | "discovery" };
type NavGroup = { label: string; items: NavItem[]; collapsible?: boolean };

const navGroups: NavGroup[] = [
  { label: "OVERVIEW", items: [{ label: "Overview", icon: "⌂", href: "/", active: "operations" }] },
  { label: "DATA", collapsible: true, items: [{ label: "Catalog", icon: "⌘", href: "/objects-flows", active: "design" }, { label: "Lineage", icon: "⌁", href: "/map-flows", active: "map" }] },
  { label: "QUALITY", collapsible: true, items: [{ label: "Rules", icon: "✓", href: "/test-plan?view=contracts&mode=manage", active: "plan", planView: "contracts" }, { label: "Compare tables", icon: "⇄", href: "/reconciliation", active: "reconciliation" }] },
  { label: "JOBS", items: [{ label: "Run jobs", icon: "⇢", href: "/actions", active: "actions" }, { label: "Monitoring", icon: "◉", href: "/monitoring", active: "monitoring" }, { label: "History", icon: "▶", href: "/test-plan?view=execution&mode=manage&tab=history", active: "plan", planView: "execution" }, { label: "Schedules", icon: "◷", href: "/test-plan?view=execution&mode=manage&tab=schedules", active: "plan", planView: "execution" }] },
  { label: "INCIDENTS", collapsible: true, items: [{ label: "Incidents", icon: "!", href: "/incidents", active: "incidents" }, { label: "Investigations", icon: "◎", href: "/investigations", active: "investigations" }] },
  { label: "ASK AI", items: [{ label: "Ask AI", icon: "✦", href: "/agent", active: "agent" }] },
  { label: "SETTINGS", collapsible: true, items: [{ label: "Project", icon: "◇", href: "/register-project?phase=overview", active: "register", setting: "project" }, { label: "Connections", icon: "↗", href: "/register-project?phase=connections", active: "register", setting: "connections" }, { label: "Discovery", icon: "▦", href: "/register-project?phase=discovery", active: "register", setting: "discovery" }] },
];

export default function DraftShell({ active, planView, children }: DraftShellProps) {
  const [workspace, setWorkspace] = useState<{ name: string; environment: string } | null>(null);
  const [mounted, setMounted] = useState(false);
  const [currentPath, setCurrentPath] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({ JOBS: true, "ASK AI": true });
  const activeGroups = useMemo(() => new Set(navGroups.filter((group) => group.items.some((item) => item.active === active)).map((group) => group.label)), [active]);
  useEffect(() => {
    let activeRequest = true;
    setMounted(true);
    setCurrentPath(`${window.location.pathname}${window.location.search}`);
    void fetch("/api/workspace", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("workspace unavailable")))
      .then((value: { name: string; environment: string }) => { if (activeRequest) setWorkspace(value); })
      .catch(() => { /* The shell remains usable while project setup is incomplete. */ });
    return () => { activeRequest = false; };
  }, []);
  return <main className={styles.shell} aria-label="Automated Data Quality control plane">
    <a className={styles.skipLink} href="#main-content">Skip to main content</a>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><span>DQ</span><div><strong>Automated DQ</strong><small>AGENTIC DATA QUALITY</small></div></div>
      <Link className={styles.workspace} href={mounted ? scopedLink("/register-project?phase=overview") : "/register-project?phase=overview"} aria-label="Open project settings"><small>WORKSPACE · {workspace?.environment ?? "loading"}</small><strong>{workspace?.name ?? "Loading project…"}</strong><b aria-hidden="true">⌄</b></Link>
      <nav aria-label="Primary navigation">
        {navGroups.map((group) => { const groupActive = activeGroups.has(group.label); const expanded = groupActive || expandedGroups[group.label] === true; const groupId = `nav-group-${group.label.toLowerCase().replaceAll(" ", "-")}`; return <div className={styles.navGroup} key={group.label}>{group.collapsible ? <button type="button" className={styles.navGroupToggle} aria-expanded={expanded} aria-controls={groupId} onClick={() => setExpandedGroups((current) => ({ ...current, [group.label]: !expanded }))}><span className={styles.navGroupLabel}>{group.label}</span><span aria-hidden="true">{expanded ? "−" : "+"}</span></button> : <p className={styles.navGroupLabel}>{group.label}</p>}<div id={groupId} hidden={Boolean(group.collapsible && !expanded)}>{group.items.map((item) => {
          const requestedPhase = currentPath.includes("phase=connections") ? "connections" : currentPath.includes("phase=discovery") ? "discovery" : "project";
          const requestedExecutionTab = currentPath.includes("tab=schedules") ? "schedules" : currentPath.includes("tab=history") ? "history" : "run";
          const itemExecutionTab = item.href.includes("tab=schedules") ? "schedules" : item.href.includes("tab=history") ? "history" : item.planView === "execution" ? "run" : null;
          const selected = item.active === active && (!item.planView || item.planView === planView || (item.active !== "plan" && !planView)) && (!item.setting || (currentPath ? item.setting === requestedPhase : item.setting === "project")) && (!itemExecutionTab || itemExecutionTab === requestedExecutionTab);
          // Preserve the server-rendered route and add project/environment
          // scope only after hydration to avoid changing deep-link behavior.
          return <Link className={selected ? styles.active : ""} aria-current={selected ? "page" : undefined} aria-label={item.label} href={mounted ? scopedLink(item.href) : item.href} key={item.label}><i aria-hidden="true">{item.icon}</i><span>{item.label}</span></Link>;
        })}</div></div>; })}
      </nav>
    </aside>
    <section className={styles.content} id="main-content" tabIndex={-1}>{children}</section>
  </main>;
}
