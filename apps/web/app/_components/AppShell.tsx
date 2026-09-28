"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

const NAV = [
  { label: "Investigate", href: "/investigations", key: "IN" },
  { label: "Airflow", href: "/airflow", key: "AF" },
  { label: "PostgreSQL", href: "/postgres", key: "PG" },
  { label: "Snowflake", href: "/snowflake", key: "SF" },
  { label: "dbt", href: "/dbt", key: "DB" },
  { label: "Quality", href: "/quality", key: "DQ" },
  { label: "Reconcile", href: "/reconciliation", key: "RC" },
  { label: "Lineage", href: "/lineage", key: "LN" },
  { label: "SQL", href: "/sql", key: "SQ" },
  { label: "Connections", href: "/connections", key: "CN" },
  { label: "Platform", href: "/platform", key: "PL" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [palette, setPalette] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const legacy = pathname.startsWith("/legacy");
  const commands = useMemo(
    () => NAV.filter((item) => `${item.label} ${item.href}`.toLowerCase().includes(query.toLowerCase())),
    [query],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((value) => !value);
      }
      if (event.key === "Escape") {
        setPalette(false);
        setMobileNav(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (palette) window.setTimeout(() => input.current?.focus(), 0);
  }, [palette]);

  useEffect(() => setMobileNav(false), [pathname]);

  if (legacy) return children;

  return (
    <div className="ade-shell">
      <aside id="ade-navigation" className={`ade-sidebar${mobileNav ? " mobile-open" : ""}`}>
        <Link href="/investigations" className="ade-brand" aria-label="ADE investigations">
          <span>A</span><strong>ADE</strong><small>CONTROL PLANE</small>
        </Link>
        <button className="mobile-nav-close" aria-label="Close workspaces" onClick={() => setMobileNav(false)}>×</button>
        <nav aria-label="Primary navigation">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} onClick={() => setMobileNav(false)} className={pathname.startsWith(item.href) ? "active" : ""}>
              <span>{item.key}</span>{item.label}
            </Link>
          ))}
        </nav>
        <div className="ade-sidebar-foot"><i />Investigation tools are read-only</div>
      </aside>
      {mobileNav && <button className="mobile-nav-backdrop" aria-label="Close workspaces" onClick={() => setMobileNav(false)} />}
      <div className="ade-main">
        <header className="ade-topbar">
          <button className="mobile-nav-trigger" aria-label="Open workspaces" aria-controls="ade-navigation" aria-expanded={mobileNav} onClick={() => setMobileNav(true)}><span>☰</span></button>
          <div className="ade-breadcrumbs">
            <Link href="/investigations">ADE</Link>
            {pathname.split("/").filter(Boolean).map((part, index) => <span key={`${part}-${index}`}>/ {decodeURIComponent(part)}</span>)}
          </div>
          <button className="command-trigger" onClick={() => setPalette(true)}>Search or jump <kbd>⌘K</kbd></button>
          <div className="environment"><i />LOCAL</div>
        </header>
        <main className="ade-workspace">{children}</main>
      </div>
      {palette && (
        <div className="command-backdrop" role="presentation" onMouseDown={() => setPalette(false)}>
          <div className="command-palette" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={(event) => event.stopPropagation()}>
            <input ref={input} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Go to a workspace…" aria-label="Command search" />
            <div>
              <button onClick={() => { setPalette(false); router.push("/investigations"); }}><span>+</span>New investigation</button>
              {commands.map((item) => <button key={item.href} onClick={() => { setPalette(false); router.push(item.href); }}><span>{item.key}</span>{item.label}</button>)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
