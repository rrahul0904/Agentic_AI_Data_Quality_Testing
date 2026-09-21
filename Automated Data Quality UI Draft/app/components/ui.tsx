"use client";

import { useEffect, useRef, type ReactNode } from "react";
import styles from "./ui.module.css";

type Tone = "good" | "warn" | "bad" | "neutral";

const statusLabels: Record<string, string> = {
  PASS: "Passed", PASSED: "Passed", COMPLETED: "Completed", VERIFIED: "Verified", READY: "Ready",
  FAILED: "Failed", FAIL: "Failed", ERROR: "Error", BLOCKED: "Blocked", UNCERTAIN: "Uncertain",
  OUTCOME_UNKNOWN: "Outcome unknown", QUEUED: "Queued", RUNNING: "Running", MONITORING: "Waiting",
  VERIFYING: "Verifying", AWAITING_APPROVAL: "Awaiting approval", AWAITING_CONTINUATION: "Awaiting continuation",
  NOT_RUN: "Not run", NOT_CHECKED: "Not checked", UNAVAILABLE: "Unavailable", STALE: "Stale",
};

function normalize(value: unknown): string { return value === null || value === undefined || value === "" ? "NOT_CHECKED" : String(value).toUpperCase(); }
function toneFor(value: unknown): Tone {
  const state = normalize(value);
  if (["PASS", "PASSED", "COMPLETED", "VERIFIED", "READY", "HEALTHY"].includes(state)) return "good";
  if (["QUEUED", "RUNNING", "MONITORING", "VERIFYING", "AWAITING_APPROVAL", "AWAITING_CONTINUATION", "PENDING", "STALE"].includes(state)) return "warn";
  if (["FAILED", "FAIL", "ERROR", "BLOCKED", "UNCERTAIN", "OUTCOME_UNKNOWN", "REJECTED"].includes(state)) return "bad";
  return "neutral";
}

export function StatusBadge({ value, tone, label }: { value?: unknown; tone?: Tone; label?: string }) {
  const state = normalize(value);
  return <span className={`${styles.badge} ${styles[tone ?? toneFor(value)]}`}>{label ?? statusLabels[state] ?? state.replaceAll("_", " ")}</span>;
}

export function PageHeader({ eyebrow, title, description, actions, status }: { eyebrow: string; title: string; description: string; actions?: ReactNode; status?: ReactNode }) {
  return <header className={styles.pageHeader}><div className={styles.pageHeaderCopy}><span className={styles.eyebrow}>{eyebrow}</span><h1>{title}</h1><p>{description}</p></div><div className={styles.pageHeaderActions}>{status}{actions}</div></header>;
}

export function EmptyState({ title, children }: { title: string; children: ReactNode }) { return <div className={styles.empty}><strong>{title}</strong><p>{children}</p></div>; }
export function ErrorState({ title = "Something went wrong", children }: { title?: string; children: ReactNode }) { return <div className={styles.error} role="alert"><strong>{title}</strong><p>{children}</p></div>; }

export function ProjectSelector({ projects, currentProjectId, onChange, disabled = false }: { projects: Array<{ id: string; name: string }>; currentProjectId: string; onChange: (id: string) => void; disabled?: boolean }) {
  return <label className={styles.projectSelector}>Project<select aria-label="Switch project" disabled={disabled} value={currentProjectId} onChange={(event) => onChange(event.target.value)}>{projects.length ? projects.map((project) => <option key={project.id} value={project.id}>{project.name || "New project"}</option>) : <option value={currentProjectId}>Current project</option>}</select></label>;
}

export function useDrawerFocus(open: boolean, onClose: () => void) {
  const closeRef = useRef(onClose);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const drawer = document.querySelector<HTMLElement>('[role="dialog"]');
    const focusable = () => Array.from(drawer?.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])") ?? []).filter((item) => !item.hasAttribute("disabled"));
    window.requestAnimationFrame(() => (drawer?.querySelector<HTMLElement>("[data-drawer-autofocus]") ?? focusable()[0] ?? drawer)?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); returnFocusRef.current?.focus(); };
  }, [open]);
}

export function Drawer({ open, title, eyebrow = "DETAILS", onClose, children, footer, labelledBy }: { open: boolean; title: string; eyebrow?: string; onClose: () => void; children: ReactNode; footer?: ReactNode; labelledBy?: string }) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const drawer = drawerRef.current;
    const focusable = () => Array.from(drawer?.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])") ?? []).filter((item) => !item.hasAttribute("disabled"));
    window.requestAnimationFrame(() => (drawer?.querySelector<HTMLElement>("[data-drawer-autofocus]") ?? focusable()[0] ?? drawer)?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); returnFocusRef.current?.focus(); };
  }, [open]);
  if (!open) return null;
  const id = labelledBy ?? "shared-drawer-title";
  return <div className={styles.drawerBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside ref={drawerRef} className={styles.drawer} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1}><header className={styles.drawerHeader}><div><span className={styles.eyebrow}>{eyebrow}</span><h2 id={id}>{title}</h2></div><button type="button" data-drawer-autofocus aria-label="Close details" className={styles.drawerClose} onClick={onClose}>×</button></header><div className={styles.drawerBody}>{children}</div>{footer && <footer className={styles.drawerFooter}>{footer}</footer>}</aside></div>;
}
