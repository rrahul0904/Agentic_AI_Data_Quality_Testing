"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import DraftShell from "../../DraftShell";
import { PageHeader } from "../../components/ui";
import { scopedApiUrl, scopedLink } from "../../../lib/client-workspace";
import styles from "../../workflow.module.css";
import local from "./page.module.css";

type Provider = { name: string; base_url?: string | null; api_key_env?: string | null; notes?: string };
type Config = { configured: boolean; source?: string; provider?: string | null; model?: string | null; api_key_env?: string | null; credential_present?: boolean; base_url?: string | null; updated_at?: string | null };

export default function AIProviderSettingsPage() {
  const router = useRouter();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [config, setConfig] = useState<Config | null>(null);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKeyEnv, setApiKeyEnv] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const selectedProvider = useMemo(() => providers.find((item) => item.name === provider), [providers, provider]);

  useEffect(() => {
    let cancelled = false;
    fetch(scopedApiUrl("/api/ai-provider"), { cache: "no-store" })
      .then(async (response) => {
        const value = await response.json() as { config?: Config; providers?: Provider[]; error?: string };
        if (!response.ok) throw new Error(value.error || "AI provider settings could not be loaded");
        if (cancelled) return;
        const nextProviders = Array.isArray(value.providers) ? value.providers : [];
        const nextConfig = value.config ?? null;
        setProviders(nextProviders);
        setConfig(nextConfig);
        setProvider(nextConfig?.provider || nextProviders[0]?.name || "");
        setModel(nextConfig?.model || "");
        setApiKeyEnv(nextConfig?.api_key_env || "");
        setBaseUrl(nextConfig?.base_url || "");
      })
      .catch((error) => { if (!cancelled) setNotice({ tone: "error", text: error instanceof Error ? error.message : "AI provider settings could not be loaded" }); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  async function save() {
    setSaving(true); setNotice(null);
    try {
      const response = await fetch(scopedApiUrl("/api/ai-provider"), { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ provider, model, api_key_env: apiKeyEnv || null, base_url: baseUrl || null }) });
      const value = await response.json() as { config?: Config; error?: string };
      if (!response.ok) throw new Error(value.error || "AI provider settings could not be saved");
      setConfig(value.config ?? null);
      setNotice({ tone: "success", text: "AI provider settings saved for this project and environment." });
      router.refresh();
    } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "AI provider settings could not be saved" }); }
    finally { setSaving(false); }
  }

  async function clearOverride() {
    setSaving(true); setNotice(null);
    try {
      const response = await fetch(scopedApiUrl("/api/ai-provider"), { method: "DELETE" });
      const value = await response.json() as { error?: string };
      if (!response.ok) throw new Error(value.error || "AI provider override could not be cleared");
      setConfig({ configured: false, source: "server_environment" });
      setModel(""); setApiKeyEnv(""); setBaseUrl("");
      setProvider(providers[0]?.name || "");
      setNotice({ tone: "success", text: "Project override cleared. Ask AI will use the server environment configuration." });
      router.refresh();
    } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "AI provider override could not be cleared" }); }
    finally { setSaving(false); }
  }

  return <DraftShell active="register"><PageHeader eyebrow="SETTINGS / AI PROVIDER" title="AI provider" description="Configure a project-specific LLM without exposing the key to the browser or storing it in the application database." actions={<a className={styles.secondary} href={scopedLink("/agent")}>Open Ask AI</a>} />
    <div className={local.layout}>
      <section className={local.panel} aria-labelledby="ai-provider-heading">
        <h2 id="ai-provider-heading">Bring your own AI provider</h2>
        <p>Choose an OpenAI-compatible provider and model for this project/environment. The server reads the key from the environment variable you name; the key itself is never sent to or returned by the UI.</p>
        <div className={local.scope}>Current scope is taken from the active project and environment.</div>
        {loading ? <p role="status">Loading provider settings…</p> : <div className={local.form}>
          <label className={local.field}>Provider<select value={provider} onChange={(event) => setProvider(event.target.value)} disabled={!providers.length || saving}><option value="">Select a provider</option>{providers.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>{selectedProvider?.notes ? <span className={local.hint}>{selectedProvider.notes}</span> : null}</label>
          <label className={local.field}>Model<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="e.g. gpt-4.1-mini" disabled={saving} /></label>
          <label className={`${local.field} ${local.wide}`}>API key environment variable<input value={apiKeyEnv} onChange={(event) => setApiKeyEnv(event.target.value)} placeholder={selectedProvider?.api_key_env || "OPENAI_API_KEY"} disabled={saving} autoComplete="off" /><span className={local.hint}>Example: <code>OPENAI_API_KEY</code>. Set that variable in the backend runtime environment before verification. Do not paste the key here.</span></label>
          <label className={`${local.field} ${local.wide}`}>Custom base URL <span className={local.hint}>Optional. Leave blank to use the provider default.</span><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder={selectedProvider?.base_url || "https://api.openai.com/v1"} disabled={saving} /></label>
        </div>}
        <div className={local.actions}><button type="button" className={local.primary} disabled={loading || saving || !provider || !model} onClick={() => void save()}>{saving ? "Saving…" : "Save provider settings"}</button><button type="button" className={local.secondary} disabled={loading || saving || !config?.configured} onClick={() => void clearOverride()}>Use server default</button></div>
        {notice ? <div className={`${local.notice} ${notice.tone === "success" ? local.success : local.error}`} role={notice.tone === "error" ? "alert" : "status"}>{notice.text}</div> : null}
      </section>
      <section className={local.panel} aria-labelledby="provider-status-heading">
        <h2 id="provider-status-heading">Configuration status</h2>
        <p>This is configuration status only. It does not claim the provider is reachable until an explicit provider verification succeeds.</p>
        <div className={local.statusGrid}><div><small>Source</small><strong>{config?.configured ? "Project settings" : "Server environment"}</strong></div><div><small>Provider</small><strong>{config?.provider || "Server default"}</strong></div><div><small>Model</small><strong>{config?.model || "Configured by server"}</strong></div><div><small>Key present</small><strong>{config?.configured ? (config.credential_present ? "Available" : "Missing") : "Not overridden"}</strong></div></div>
        <p className={local.warning}>A saved configuration is not a live health result. Use the explicit provider verification in Ask AI diagnostics when you need to check connectivity.</p>
      </section>
    </div>
  </DraftShell>;
}
