"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ProjectManagementShell from "../ProjectManagementShell";
import styles from "../workflow.module.css";
import ScopedLink from "../components/ScopedLink";
import type { QualityCheck, QualityPlan, QualityPlanRevision, QualityPlanRun, QualityPlanRunSummary, QualityPlanWorkspace, QualityRunRequest, QualitySchedule } from "../../lib/quality-plan";
import type { OnboardingBootstrap } from "../../lib/onboarding";
import { currentWorkspaceParams, scopedApiUrl } from "../../lib/client-workspace";
import { useDrawerFocus } from "../components/ui";

type View = "contracts" | "execution";
type WorkspaceMode = "review" | "manage";
type ExecutionTab = "run" | "history" | "schedules";
type RuleDraft = {
  minRows: number; maxRows: string; columns: string; maxNullPercentage: number; maxDuplicateGroups: number;
  column: string; allowedValues: string; maxInvalidCount: number; maxAgeMinutes: number;
  expectedColumns: string; allowExtraColumns: boolean; targetSchema: string; targetTable: string;
  targetColumns: string; maxOrphanCount: number; sql: string; expectation: "NO_ROWS" | "ZERO"; persistSample: boolean;
};

const contractTypes = ["PROFILE", "VOLUME", "COMPLETENESS", "UNIQUENESS", "VALIDITY", "FRESHNESS", "SCHEMA", "REFERENTIAL_INTEGRITY", "CUSTOM_SQL"] as const;
const contractHelp: Record<string, string> = {
  PROFILE: "Measure row count and, when a key is known, check null and duplicate keys.",
  VOLUME: "Fail when the object contains fewer or more rows than the approved range.",
  COMPLETENESS: "Measure nulls in selected columns and compare them with an approved tolerance.",
  UNIQUENESS: "Detect duplicate groups for one column or a composite key.",
  VALIDITY: "Ensure values belong to an approved list.",
  FRESHNESS: "Compare the newest timestamp with the approved maximum age.",
  SCHEMA: "Verify required columns and optionally reject unexpected columns.",
  REFERENTIAL_INTEGRITY: "Detect source keys that have no matching record in another table.",
  CUSTOM_SQL: "Run one bounded read-only SELECT and evaluate whether it returns failures.",
};

const initialRuleDraft: RuleDraft = {
  minRows: 1, maxRows: "", columns: "", maxNullPercentage: 0, maxDuplicateGroups: 0,
  column: "", allowedValues: "", maxInvalidCount: 0, maxAgeMinutes: 60,
  expectedColumns: "", allowExtraColumns: true, targetSchema: "", targetTable: "",
  targetColumns: "", maxOrphanCount: 0, sql: "", expectation: "NO_ROWS", persistSample: false,
};
const CHECK_PAGE_SIZE = 25;

function serializedCheck(item: QualityCheck): Record<string, unknown> {
  return {
    check_id: item.check_id,
    enabled: item.enabled,
    archived: Boolean(item.archived),
    severity: item.severity,
    key_column: Array.isArray(item.params.key_columns) ? item.params.key_columns.join(", ") : "",
    contract: item.params.contract,
    name: item.name,
  };
}

function valueText(value: unknown, fallback = "Not recorded"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function ruleStatus(check: QualityCheck, plan: QualityPlan, latestRun?: QualityPlanRun | null): string {
  if (check.archived) return "ARCHIVED";
  const result = latestRun?.results.find((item) => item.check_id === check.check_id);
  if (result && ["FAIL", "ERROR"].includes(result.status)) return "FAILED";
  if (!check.enabled) return "DISABLED";
  return plan.status === "DRAFT" ? "DRAFT" : "ACTIVE";
}

function ruleAssetLabel(check: QualityCheck, plan: QualityPlan): string {
  const mapping = plan.mappings.find((item) => item.mapping_id === check.mapping_id);
  if (mapping) return `${mapping.source_name} → ${mapping.target_name}`;
  const params = check.params ?? {};
  const objectName = [params.database, params.schema, params.table].filter(Boolean).join(".");
  return valueText(params.path ?? objectName, "Project asset");
}

function ruleExpectation(check: QualityCheck): string {
  const contract = check.params.contract && typeof check.params.contract === "object" ? check.params.contract as Record<string, unknown> : {};
  const type = String(contract.type ?? check.category).replaceAll("_", " ");
  if (contract.min_rows !== undefined || contract.max_rows !== undefined) return `Rows ${contract.min_rows ?? 0}${contract.max_rows !== undefined ? `–${contract.max_rows}` : "+"}`;
  if (contract.max_null_percentage !== undefined) return `Nulls ≤ ${contract.max_null_percentage}%`;
  if (contract.max_duplicate_groups !== undefined) return `Duplicates ≤ ${contract.max_duplicate_groups}`;
  if (Array.isArray(contract.allowed_values)) return `Allowed: ${contract.allowed_values.slice(0, 3).map(String).join(", ")}${contract.allowed_values.length > 3 ? "…" : ""}`;
  if (contract.column) return `${type} · ${String(contract.column)}`;
  if (Array.isArray(contract.expected_columns)) return `${contract.expected_columns.length} required columns`;
  if (contract.target_table) return `Matches ${String(contract.target_table)}`;
  return type;
}

function latestRuleResult(check: QualityCheck, latestRun?: QualityPlanRun | null): string {
  return latestRun?.results.find((item) => item.check_id === check.check_id)?.status ?? "NOT RUN";
}

function commaSeparated(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

async function request(payload?: Record<string, unknown>, query?: Record<string, string | number>): Promise<Record<string, unknown>> {
  const queryString = query ? `?${new URLSearchParams(Object.entries(query).map(([key, value]) => [key, String(value)]))}` : "";
  const response = await fetch(scopedApiUrl(`/api/quality-plans${queryString}`), payload ? {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  } : { cache: "no-store" });
  const value = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof value.error === "string" ? value.error : `Request failed (${response.status})`);
  return value;
}

function evidenceSource(value: unknown): string {
  if (typeof value === "string" && value.trim()) return value;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => typeof item === "string" || typeof item === "number")
      .map(([key, item]) => `${key}: ${String(item)}`);
    if (entries.length) return entries.join(" · ");
  }
  return "Persisted connector result";
}

export default function QualityPlanPage() {
  const [view, setView] = useState<View>("contracts");
  const [mode, setMode] = useState<WorkspaceMode>("review");
  const [executionTab, setExecutionTab] = useState<ExecutionTab>("run");
  const [workspaceQuery, setWorkspaceQuery] = useState("");
  const [plan, setPlan] = useState<QualityPlan | null>(null);
  const [runs, setRuns] = useState<QualityPlanRunSummary[]>([]);
  const [runDetails, setRunDetails] = useState<Record<string, QualityPlanRun>>({});
  const [runPage, setRunPage] = useState(1);
  const [runTotal, setRunTotal] = useState(0);
  const [runHasNext, setRunHasNext] = useState(false);
  const [revisions, setRevisions] = useState<QualityPlanRevision[]>([]);
  const [schedules, setSchedules] = useState<QualitySchedule[]>([]);
  const [runRequests, setRunRequests] = useState<QualityRunRequest[]>([]);
  const [capabilities, setCapabilities] = useState<Record<string, unknown>>({});
  const [automationCapabilities, setAutomationCapabilities] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [workspaceLoaded, setWorkspaceLoaded] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [workspaceReload, setWorkspaceReload] = useState(0);
  const [category, setCategory] = useState("ALL");
  const [ruleFilter, setRuleFilter] = useState("ALL");
  const [checkQuery, setCheckQuery] = useState("");
  const [checkPage, setCheckPage] = useState(1);
  const [scheduleType, setScheduleType] = useState<"INTERVAL" | "EVENT">("INTERVAL");
  const [intervalMinutes, setIntervalMinutes] = useState(60);
  const [eventName, setEventName] = useState("airflow.dag.success");
  const [newContractType, setNewContractType] = useState("VOLUME");
  const [newContractTarget, setNewContractTarget] = useState("");
  const [newRule, setNewRule] = useState<RuleDraft>(initialRuleDraft);
  const [onboarding, setOnboarding] = useState<OnboardingBootstrap | null>(null);
  const [selectedCheckId, setSelectedCheckId] = useState<string | null>(null);
  const [editingCheckId, setEditingCheckId] = useState<string | null>(null);
  const [savedPlanFingerprint, setSavedPlanFingerprint] = useState("");
  useDrawerFocus(Boolean(selectedCheckId), () => { setSelectedCheckId(null); setEditingCheckId(null); });

  const applyWorkspace = (workspace: QualityPlanWorkspace) => {
    setPlan(workspace.plan); setRuns(workspace.runs); setRevisions(workspace.revisions ?? []);
    setSchedules(workspace.schedules ?? []); setRunRequests(workspace.requests ?? []);
    setRunPage(workspace.runPage ?? 1); setRunTotal(workspace.runTotal ?? workspace.runs.length); setRunHasNext(Boolean(workspace.runHasNext));
    setCapabilities(workspace.capabilities); setAutomationCapabilities(workspace.automationCapabilities ?? {});
    setSavedPlanFingerprint(workspace.plan ? JSON.stringify(workspace.plan) : "");
  };

  useEffect(() => {
    setWorkspaceLoading(true);
    setWorkspaceError(null);
    const params = new URLSearchParams(window.location.search);
    setWorkspaceQuery(currentWorkspaceParams().toString());
    setView(params.get("view") === "execution" ? "execution" : "contracts");
    setMode(params.get("mode") === "manage" ? "manage" : "review");
    const requestedTab = params.get("tab");
    setExecutionTab(requestedTab === "history" || requestedTab === "schedules" ? requestedTab : "run");
    void fetch(scopedApiUrl("/api/onboarding"), { cache: "no-store" }).then((response) => response.ok ? response.json() as Promise<OnboardingBootstrap> : Promise.reject(new Error("onboarding unavailable"))).then(setOnboarding).catch(() => setOnboarding(null));
    request().then((value) => {
      const workspace = value as unknown as QualityPlanWorkspace;
      applyWorkspace(workspace);
    }).catch((error: Error) => {
      const message = error.message || "Runs and evidence are unavailable";
      setWorkspaceError(message);
      setNotice(message);
    }).finally(() => {
      setWorkspaceLoading(false);
      setWorkspaceLoaded(true);
    });
  }, [workspaceReload]);

  const executionHref = (tab: ExecutionTab): string => {
    const base = `/test-plan?view=execution&mode=manage&tab=${tab}`;
    return workspaceQuery ? `${base}&${workspaceQuery}` : base;
  };

  const mutate = async (action: string, extra: Record<string, unknown> = {}) => {
    setBusy(action); setNotice(null);
    try {
      const value = await request({ action, planId: plan?.plan_id, ...extra });
      if (value.plan || value.request || value.schedule) {
        const workspace = await request() as unknown as QualityPlanWorkspace;
        applyWorkspace(workspace);
      }
      if (value.run) {
        const run = value.run as unknown as QualityPlanRun;
        setRunDetails((current) => ({ ...current, [run.run_id]: run }));
        setNotice(`Live execution completed with status ${run.status}.`);
      } else {
        setNotice(action === "generate" ? "A fresh plan was generated from the latest evidence graph." : action === "approve" ? "Plan approved and unlocked for execution." : action === "queue" ? "Execution request queued with a persistent idempotency key." : action.includes("Schedule") ? "Automation schedule updated and persisted." : action === "cancelRequest" ? "Cancellation request persisted." : "Plan changes saved; approval is required again.");
      }
    } catch (error) { setNotice(error instanceof Error ? error.message : "Operation failed"); }
    finally { setBusy(null); }
  };

  const loadRunPage = async (page: number) => {
    setBusy("history"); setNotice(null);
    try {
      const value = await request(undefined, { run_page: page, run_page_size: 10 });
      applyWorkspace(value as unknown as QualityPlanWorkspace);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Run history is unavailable"); }
    finally { setBusy(null); }
  };

  useEffect(() => {
    const summary = runs[0];
    if (!summary || runDetails[summary.run_id] || !plan?.plan_id) return;
    let cancelled = false;
    fetch(scopedApiUrl(`/api/quality-plans/runs/${encodeURIComponent(summary.run_id)}?plan_id=${encodeURIComponent(plan.plan_id)}`), { cache: "no-store", signal: AbortSignal.timeout(4000) })
      .then((response) => response.ok ? response.json() as Promise<QualityPlanRun> : Promise.reject(new Error("Latest run details are unavailable")))
      .then((detail) => { if (!cancelled) setRunDetails((current) => ({ ...current, [detail.run_id]: detail })); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [plan?.plan_id, runDetails, runs]);

  useEffect(() => {
    if (!runRequests.some((item) => ["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(item.status))) return;
    const timer = window.setInterval(() => {
      request().then((value) => {
        const workspace = value as unknown as QualityPlanWorkspace;
        setRuns(workspace.runs); setRunRequests(workspace.requests ?? []); setSchedules(workspace.schedules ?? []);
      }).catch((error: Error) => setNotice(error.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [runRequests]);

  const planDirty = Boolean(plan && savedPlanFingerprint && JSON.stringify(plan) !== savedPlanFingerprint);
  useEffect(() => {
    if (!planDirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [planDirty]);
  useEffect(() => {
    if (!editingCheckId) return;
    const timer = window.setTimeout(() => document.getElementById("rule-edit-form")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    return () => window.clearTimeout(timer);
  }, [editingCheckId]);

  const updateCheck = (checkId: string, changes: Partial<QualityCheck>) => {
    setPlan((current) => current ? { ...current, checks: current.checks.map((item) => item.check_id === checkId ? { ...item, ...changes } : item) } : current);
  };
  const updateMappingKey = (mappingId: string, keyColumn: string) => {
    setPlan((current) => current ? {
      ...current,
      mappings: current.mappings.map((item) => item.mapping_id === mappingId ? { ...item, key_column: keyColumn || null } : item),
      checks: current.checks.map((item) => item.mapping_id === mappingId ? { ...item, params: { ...item.params, key_columns: keyColumn.split(",").map((part) => part.trim()).filter(Boolean) } } : item),
    } : current);
  };
  const updateContract = (checkId: string, field: string, value: string | number | boolean) => {
    setPlan((current) => current ? {
      ...current,
      checks: current.checks.map((item) => {
        if (item.check_id !== checkId) return item;
        const contract = item.params.contract && typeof item.params.contract === "object" ? item.params.contract as Record<string, unknown> : {};
        return { ...item, params: { ...item.params, contract: { ...contract, [field]: value } } };
      }),
    } : current);
  };
  const save = () => void mutate("update", {
    name: plan?.name,
    checks: plan?.checks.map(serializedCheck),
  });
  const saveCurrentRule = () => { save(); setEditingCheckId(null); };
  const archiveRule = (check: QualityCheck) => {
    if (!plan || check.archived) return;
    if (!window.confirm(`Archive “${check.name}”? Its history will be preserved and it will no longer execute.`)) return;
    const nextPlan = { ...plan, checks: plan.checks.map((item) => item.check_id === check.check_id ? { ...item, archived: true, enabled: false } : item) };
    setPlan(nextPlan);
    void mutate("update", { name: nextPlan.name, checks: nextPlan.checks.map(serializedCheck) });
    setSelectedCheckId(null);
  };
  const duplicateRule = (check: QualityCheck) => {
    if (!plan) return;
    void mutate("update", {
      addChecks: [{
        mapping_id: check.mapping_id, name: `Copy of ${check.name}`, category: check.category,
        executor: check.executor, severity: check.severity, enabled: false, archived: false,
        requires_review: true, provenance: "OPERATOR_DEFINED", evidence: "Duplicated from an existing operator-reviewed rule.",
        params: check.params,
      }],
    });
  };
  const toggleRule = (check: QualityCheck, enabled: boolean) => {
    if (!plan || check.archived) return;
    const nextPlan = { ...plan, checks: plan.checks.map((item) => item.check_id === check.check_id ? { ...item, enabled } : item) };
    setPlan(nextPlan);
    void mutate("update", { name: nextPlan.name, checks: nextPlan.checks.map(serializedCheck) });
  };
  const buildNewContract = (): Record<string, unknown> => {
    const columns = commaSeparated(newRule.columns);
    if (newContractType === "PROFILE") return { type: "PROFILE" };
    if (newContractType === "VOLUME") return { type: "VOLUME", min_rows: newRule.minRows, ...(newRule.maxRows.trim() ? { max_rows: Number(newRule.maxRows) } : {}) };
    if (newContractType === "COMPLETENESS") {
      if (!columns.length) throw new Error("Choose at least one column for the completeness rule.");
      return { type: "COMPLETENESS", columns, max_null_count: 0, max_null_percentage: newRule.maxNullPercentage };
    }
    if (newContractType === "UNIQUENESS") {
      if (!columns.length) throw new Error("Choose at least one key column for the uniqueness rule.");
      return { type: "UNIQUENESS", columns, max_duplicate_groups: newRule.maxDuplicateGroups };
    }
    if (newContractType === "VALIDITY") {
      const allowedValues = commaSeparated(newRule.allowedValues);
      if (!newRule.column.trim() || !allowedValues.length) throw new Error("Choose a column and at least one allowed value.");
      return { type: "VALIDITY", column: newRule.column.trim(), allowed_values: allowedValues, max_invalid_count: newRule.maxInvalidCount };
    }
    if (newContractType === "FRESHNESS") {
      if (!newRule.column.trim()) throw new Error("Choose the timestamp column used to measure freshness.");
      return { type: "FRESHNESS", column: newRule.column.trim(), max_age_minutes: newRule.maxAgeMinutes };
    }
    if (newContractType === "SCHEMA") {
      const expected = commaSeparated(newRule.expectedColumns);
      if (!expected.length) throw new Error("Enter at least one required column.");
      return { type: "SCHEMA", expected_columns: expected.map((name) => ({ name })), allow_extra_columns: newRule.allowExtraColumns };
    }
    if (newContractType === "REFERENTIAL_INTEGRITY") {
      const targetColumns = commaSeparated(newRule.targetColumns);
      if (!columns.length || !newRule.targetSchema.trim() || !newRule.targetTable.trim() || columns.length !== targetColumns.length) throw new Error("Source and target columns must be present and have the same count.");
      return { type: "REFERENTIAL_INTEGRITY", columns, target_schema: newRule.targetSchema.trim(), target_table: newRule.targetTable.trim(), target_columns: targetColumns, max_orphan_count: newRule.maxOrphanCount };
    }
    if (!newRule.sql.trim()) throw new Error("Enter a bounded read-only SELECT statement.");
    return { type: "CUSTOM_SQL", sql: newRule.sql.trim(), expectation: newRule.expectation, persist_sample: newRule.persistSample };
  };
  const addContract = () => {
    if (!plan || !newContractTarget) { setNotice("Choose a data or pipeline object before creating a rule."); return; }
    try {
      const mapping = plan.mappings.find((item) => item.source_asset_id === newContractTarget || item.target_asset_id === newContractTarget);
      if (!mapping) throw new Error("The selected object is not attached to an evidence-supported mapping.");
      const selected = mapping.source_asset_id === newContractTarget ? mapping.source_name : mapping.target_name;
      const lower = selected.toLowerCase();
      const platform = lower.endsWith(".csv") || lower.endsWith(".parquet") ? "file" : lower.startsWith("postgres.") ? "postgres" : "snowflake";
      const qualified = selected.split(".");
      const params: Record<string, unknown> = { platform, schema: platform === "file" ? undefined : qualified.at(-2), table: platform === "file" ? undefined : qualified.at(-1), path: platform === "file" ? selected : undefined, contract: buildNewContract() };
      void mutate("update", { addChecks: [{ name: `${newContractType} ${selected}`, category: "DATA_QUALITY", params, enabled: false, requires_review: true, provenance: "OPERATOR_DEFINED", evidence: "Added by operator; requires approval before execution." }] });
    } catch (error) { setNotice(error instanceof Error ? error.message : "The quality rule is incomplete."); }
  };
  const categories = useMemo(() => ["ALL", ...new Set(plan?.checks.map((item) => item.category) ?? [])], [plan]);
  const latestRun = runs[0] ? runDetails[runs[0].run_id] ?? null : null;
  const latestRunLoading = Boolean(runs[0] && !latestRun);
  const initialWorkspaceLoading = workspaceLoading && !workspaceLoaded;
  const retryWorkspace = () => { setNotice(null); setWorkspaceReload((current) => current + 1); };
  const hasCurrentEvidence = Boolean(onboarding && (
    Object.values(onboarding.savedTests ?? {}).some((item) => item.status === "PASS")
    || Object.values(onboarding.savedDiscoveries ?? {}).some((item) => item.status === "PASS")
    || onboarding.selectedAssets.length > 0
  ));
  const visibleChecks = useMemo(() => {
    const query = checkQuery.trim().toLowerCase();
    return (plan?.checks ?? []).filter((item) => {
      if (category !== "ALL" && item.category !== category) return false;
      const result = latestRun?.results.find((runResult) => runResult.check_id === item.check_id);
      if (ruleFilter === "ARCHIVED" && !item.archived) return false;
      if (ruleFilter === "FAILED" && (!result || !["FAIL", "ERROR"].includes(result.status))) return false;
      if (ruleFilter === "NEEDS_REVIEW" && !item.requires_review) return false;
      if (ruleFilter === "ACTIVE" && (item.archived || !item.enabled)) return false;
      return !query || [item.name, item.category, item.executor, item.provenance, item.evidence]
        .filter((value): value is string => typeof value === "string")
        .some((value) => value.toLowerCase().includes(query));
    });
  }, [category, checkQuery, latestRun, plan, ruleFilter]);
  const checkPageCount = Math.max(1, Math.ceil(visibleChecks.length / CHECK_PAGE_SIZE));
  const pagedChecks = visibleChecks.slice((checkPage - 1) * CHECK_PAGE_SIZE, checkPage * CHECK_PAGE_SIZE);
  useEffect(() => { setCheckPage(1); }, [category, checkQuery, ruleFilter]);
  useEffect(() => { if (checkPage > checkPageCount) setCheckPage(checkPageCount); }, [checkPage, checkPageCount]);
  const selectedCheck = plan?.checks.find((item) => item.check_id === selectedCheckId) ?? null;
  const selectedMapping = selectedCheck && plan ? plan.mappings.find((item) => item.mapping_id === selectedCheck.mapping_id) ?? null : null;
  const selectedRunResult = selectedCheck && latestRun ? latestRun.results.find((item) => item.check_id === selectedCheck.check_id) : null;
  const adapters = (capabilities.profile_adapters ?? {}) as Record<string, string>;
  const activeRequestStates = ["QUEUED", "RUNNING", "CANCEL_REQUESTED"];
  const schedulerPollSeconds = Number(automationCapabilities.scheduler_poll_seconds ?? 0);
  const mappedObjects = useMemo(() => {
    const values = new Map<string, string>();
    for (const mapping of plan?.mappings ?? []) {
      values.set(mapping.source_asset_id, mapping.source_name);
      values.set(mapping.target_asset_id, mapping.target_name);
    }
    return [...values.entries()].map(([id, label]) => ({ id, label })).sort((left, right) => left.label.localeCompare(right.label));
  }, [plan]);
  const discoveredColumns = useMemo(() => {
    const tables = onboarding?.selectedSourceTables ?? (onboarding?.selectedSourceTable ? [onboarding.selectedSourceTable] : []);
    return [...new Set(tables.flatMap((table) => table.columns.map((column) => column.name).filter(Boolean)))].sort();
  }, [onboarding]);
  const discoveredTables = useMemo(() => mappedObjects.map((item) => item.label), [mappedObjects]);
  const updateNewRule = <K extends keyof RuleDraft,>(key: K, value: RuleDraft[K]) => setNewRule((current) => ({ ...current, [key]: value }));
  const ruleFields = <div className={styles.ruleFields}>
    {newContractType === "VOLUME" && <><label className={styles.field}>Minimum rows<input type="number" min="0" value={newRule.minRows} onChange={(event) => updateNewRule("minRows", Number(event.target.value))} /></label><label className={styles.field}>Maximum rows <small>Optional</small><input type="number" min="0" value={newRule.maxRows} onChange={(event) => updateNewRule("maxRows", event.target.value)} placeholder="No maximum" /></label></>}
    {["COMPLETENESS", "UNIQUENESS", "REFERENTIAL_INTEGRITY"].includes(newContractType) && <label className={`${styles.field} ${styles.wide}`}>{newContractType === "UNIQUENESS" ? "Key columns" : newContractType === "REFERENTIAL_INTEGRITY" ? "Source columns" : "Columns to inspect"}<input list="quality-rule-columns" value={newRule.columns} onChange={(event) => updateNewRule("columns", event.target.value)} placeholder="guest_id, reservation_id" /><small>{discoveredColumns.length ? "Suggestions come from discovered source columns; comma-separated values remain supported." : "No discovered columns are available yet; enter a column name."}</small></label>}
    {newContractType === "COMPLETENESS" && <label className={styles.field}>Maximum null percentage<input type="number" min="0" max="100" step="0.1" value={newRule.maxNullPercentage} onChange={(event) => updateNewRule("maxNullPercentage", Number(event.target.value))} /></label>}
    {newContractType === "UNIQUENESS" && <label className={styles.field}>Allowed duplicate groups<input type="number" min="0" value={newRule.maxDuplicateGroups} onChange={(event) => updateNewRule("maxDuplicateGroups", Number(event.target.value))} /></label>}
    {["VALIDITY", "FRESHNESS"].includes(newContractType) && <label className={styles.field}>Column<input list="quality-rule-columns" value={newRule.column} onChange={(event) => updateNewRule("column", event.target.value)} placeholder={newContractType === "FRESHNESS" ? "updated_at" : "status"} /></label>}
    {newContractType === "VALIDITY" && <><label className={`${styles.field} ${styles.wide}`}>Allowed values<input value={newRule.allowedValues} onChange={(event) => updateNewRule("allowedValues", event.target.value)} placeholder="active, inactive, pending" /><small>Separate values with commas.</small></label><label className={styles.field}>Allowed invalid rows<input type="number" min="0" value={newRule.maxInvalidCount} onChange={(event) => updateNewRule("maxInvalidCount", Number(event.target.value))} /></label></>}
    {newContractType === "FRESHNESS" && <label className={styles.field}>Maximum age in minutes<input type="number" min="1" value={newRule.maxAgeMinutes} onChange={(event) => updateNewRule("maxAgeMinutes", Number(event.target.value))} /></label>}
    {newContractType === "SCHEMA" && <><label className={`${styles.field} ${styles.wide}`}>Required columns<input list="quality-rule-columns" value={newRule.expectedColumns} onChange={(event) => updateNewRule("expectedColumns", event.target.value)} placeholder="guest_id, email, updated_at" /><small>The saved rule compares these names with live schema metadata.</small></label><label className={styles.checkField}><input type="checkbox" checked={newRule.allowExtraColumns} onChange={(event) => updateNewRule("allowExtraColumns", event.target.checked)} /><span><strong>Allow additional columns</strong><small>Required columns must remain present.</small></span></label></>}
    {newContractType === "REFERENTIAL_INTEGRITY" && <><label className={styles.field}>Target schema<input value={newRule.targetSchema} onChange={(event) => updateNewRule("targetSchema", event.target.value)} placeholder="analytics" /></label><label className={styles.field}>Target table<input list="quality-rule-tables" value={newRule.targetTable} onChange={(event) => updateNewRule("targetTable", event.target.value)} placeholder="dim_guests" /></label><label className={`${styles.field} ${styles.wide}`}>Target columns<input list="quality-rule-columns" value={newRule.targetColumns} onChange={(event) => updateNewRule("targetColumns", event.target.value)} placeholder="guest_id" /><small>Use the same number and order as the source columns.</small></label><label className={styles.field}>Allowed orphan rows<input type="number" min="0" value={newRule.maxOrphanCount} onChange={(event) => updateNewRule("maxOrphanCount", Number(event.target.value))} /></label></>}
    {newContractType === "CUSTOM_SQL" && <><label className={`${styles.field} ${styles.wide}`}>Read-only SELECT<textarea value={newRule.sql} onChange={(event) => updateNewRule("sql", event.target.value)} placeholder="SELECT ... WHERE ..." /></label><label className={styles.field}>Pass when<select value={newRule.expectation} onChange={(event) => updateNewRule("expectation", event.target.value as RuleDraft["expectation"])}><option value="NO_ROWS">Query returns no rows</option><option value="ZERO">First value equals zero</option></select></label><label className={styles.checkField}><input type="checkbox" checked={newRule.persistSample} onChange={(event) => updateNewRule("persistSample", event.target.checked)} /><span><strong>Persist bounded failure sample</strong><small>Stores at most ten returned rows.</small></span></label></>}
    {newContractType === "PROFILE" && <div className={styles.ruleInfo}><strong>No threshold is required.</strong><span>The executor records row count and uses an approved mapping key, when available, for null and duplicate checks.</span></div>}
  </div>;
  const contractAuthoring = view === "contracts" && mode === "manage" && plan ? <details className={styles.ruleBuilder}><summary><span>+</span><div><strong>Create a quality rule</strong><small>Choose where the rule runs and define its expectation with guided fields.</small></div></summary><section><div className={styles.ruleBuilderGrid}><label className={styles.field}>Data or pipeline object<select aria-label="Quality rule object" value={newContractTarget} onChange={(event) => setNewContractTarget(event.target.value)}><option value="">Choose an object from a detected mapping</option>{mappedObjects.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><label className={styles.field}>What should be tested?<select aria-label="Quality rule type" value={newContractType} onChange={(event) => setNewContractType(event.target.value)}>{contractTypes.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label></div><div className={styles.ruleExplanation}><strong>{newContractType.replaceAll("_", " ")}</strong><span>{contractHelp[newContractType]}</span></div>{ruleFields}<datalist id="quality-rule-columns">{discoveredColumns.map((column) => <option key={column} value={column} />)}</datalist><datalist id="quality-rule-tables">{discoveredTables.map((table) => <option key={table} value={table} />)}</datalist><footer><span>Saving creates a new draft revision. A human must approve the resulting rule set before execution.</span><button className={styles.primary} disabled={busy !== null || plan.status === "APPROVED"} onClick={addContract}>Create draft rule</button></footer></section></details> : null;
  const contractEditor = (item: QualityCheck) => {
    const contract = item.params.contract && typeof item.params.contract === "object" ? item.params.contract as Record<string, unknown> : null;
    if (!contract) return <span className={styles.muted}>Runtime adapter check</span>;
    const type = String(contract.type || "PROFILE");
    if (type === "VOLUME") return <label className={styles.inlineField}>Min rows<input aria-label={`Minimum rows for ${item.name}`} type="number" min="0" value={Number(contract.min_rows ?? 0)} onChange={(event) => updateContract(item.check_id, "min_rows", Number(event.target.value))} /></label>;
    if (type === "COMPLETENESS") return <label className={styles.inlineField}>Max null %<input aria-label={`Maximum null percentage for ${item.name}`} type="number" min="0" step="0.1" value={Number(contract.max_null_percentage ?? 0)} onChange={(event) => updateContract(item.check_id, "max_null_percentage", Number(event.target.value))} /></label>;
    if (type === "UNIQUENESS") return <label className={styles.inlineField}>Max duplicates<input aria-label={`Maximum duplicate groups for ${item.name}`} type="number" min="0" value={Number(contract.max_duplicate_groups ?? 0)} onChange={(event) => updateContract(item.check_id, "max_duplicate_groups", Number(event.target.value))} /></label>;
    if (type === "SCHEMA") return <label className={styles.inlineField}><span>Allow extra</span><input aria-label={`Allow extra columns for ${item.name}`} type="checkbox" checked={Boolean(contract.allow_extra_columns ?? true)} onChange={(event) => updateContract(item.check_id, "allow_extra_columns", event.target.checked)} /></label>;
    return <span className={styles.muted}>{type} · observed columns</span>;
  };

  const detailsDrawer = selectedCheck && plan ? (() => {
    const params = selectedCheck.params ?? {};
    const contract = params.contract && typeof params.contract === "object" ? params.contract as Record<string, unknown> : {};
    const status = ruleStatus(selectedCheck, plan, latestRun ?? undefined);
    const sourceObject = selectedMapping?.source_name ?? [params.source_schema, params.source_table, params.schema, params.table, params.path].filter(Boolean).join(".");
    const targetObject = selectedMapping?.target_name ?? [params.target_schema, params.target_table].filter(Boolean).join(".");
    const historicalRuns = runs.filter((run) => runDetails[run.run_id]?.results.some((result) => result.check_id === selectedCheck.check_id)).slice(0, 5);
    return <div className={styles.drawerBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) { setSelectedCheckId(null); setEditingCheckId(null); } }}><aside className={styles.ruleDrawer} role="dialog" aria-modal="true" aria-labelledby="rule-details-title"><header className={styles.drawerHeader}><div><span className={styles.eyebrow}>RULE DETAILS</span><h2 id="rule-details-title">{selectedCheck.name}</h2><div className={styles.drawerBadges}><span className={styles.ruleId}>{selectedCheck.check_id}</span><span className={`${styles.ruleStatus} ${styles[`ruleStatus${status.replaceAll("_", "")}`] ?? ""}`}>{status}</span></div></div><button className={styles.drawerClose} aria-label="Close rule details" onClick={() => { setSelectedCheckId(null); setEditingCheckId(null); }}>×</button></header><div className={styles.drawerBody}><section className={styles.drawerSection}><h3>Definition</h3><dl className={styles.detailGrid}><div><dt>Rule type</dt><dd>{valueText(contract.type, selectedCheck.category.replaceAll("_", " "))}</dd></div><div><dt>Category</dt><dd>{selectedCheck.category.replaceAll("_", " ")}</dd></div><div><dt>Severity</dt><dd>{selectedCheck.severity}</dd></div><div><dt>Execution</dt><dd>{valueText(selectedCheck.executor, "Adapter required")}</dd></div><div><dt>Threshold / expectation</dt><dd>{Object.entries(contract).filter(([key]) => key !== "type").map(([key, value]) => `${key.replaceAll("_", " ")}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`).join(" · ") || "No explicit threshold"}</dd></div><div><dt>Evidence state</dt><dd>{selectedCheck.requires_review ? "Needs confirmation" : "Evidence backed"}</dd></div></dl></section><section className={styles.drawerSection}><h3>Tables and columns</h3><dl className={styles.detailGrid}><div><dt>Source</dt><dd>{valueText(sourceObject)}</dd></div><div><dt>Target</dt><dd>{valueText(targetObject)}</dd></div><div><dt>Comparison key</dt><dd>{valueText(Array.isArray(params.key_columns) ? params.key_columns.join(", ") : "", selectedMapping?.key_inference || "Not recorded")}</dd></div><div><dt>Mapping</dt><dd>{valueText(selectedCheck.mapping_id)}</dd></div></dl></section><section className={styles.drawerSection}><h3>Ingestion and transformation</h3><dl className={styles.detailGrid}><div><dt>Pipeline objects</dt><dd>{selectedMapping?.orchestrator_asset_ids.length ? selectedMapping.orchestrator_asset_ids.join(" → ") : selectedCheck.category.includes("INGESTION") ? "Runtime ingestion check" : "Not recorded"}</dd></div><div><dt>Transformation</dt><dd>{selectedCheck.executor === "dbt_test" || selectedCheck.category.includes("TRANSFORMATION") ? valueText(params.dbt_project ?? params.project, "dbt execution context") : "Not recorded"}</dd></div><div><dt>Parameters</dt><dd>{Object.entries(params).filter(([key]) => key !== "contract" && key !== "key_columns").map(([key, value]) => `${key.replaceAll("_", " ")}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`).join(" · ") || "Not recorded"}</dd></div></dl></section><section className={styles.drawerSection}><h3>Lineage and evidence</h3><p className={styles.drawerEvidence}>{valueText(selectedCheck.evidence || selectedCheck.provenance)}</p><div className={styles.lineagePath}>{(selectedMapping?.path_asset_ids ?? []).map((assetId, index) => <span key={assetId}><strong>{assetId}</strong>{index < (selectedMapping?.path_asset_ids.length ?? 0) - 1 && <b>→</b>}</span>)}{!selectedMapping?.path_asset_ids.length && <span>Lineage path not recorded for this rule.</span>}</div><small className={styles.drawerMuted}>{valueText(selectedMapping?.key_inference, "No key inference recorded")}</small></section><section className={styles.drawerSection}><h3>Last run and history</h3>{latestRunLoading ? <p className={styles.drawerMuted}>Loading latest run details…</p> : selectedRunResult ? <div className={styles.lastResult}><span className={`${styles.evidence} ${selectedRunResult.status === "PASS" ? styles.parsed : styles.conflict}`}>{selectedRunResult.status}</span><p>{evidenceSource(selectedRunResult.result.source)}</p></div> : <p className={styles.drawerMuted}>This rule has no result in the latest persisted run.</p>}<div className={styles.historyList}>{historicalRuns.map((run) => { const result = runDetails[run.run_id]?.results.find((item) => item.check_id === selectedCheck.check_id); return <div key={run.run_id}><span>{new Date(run.started_at).toLocaleString()}</span><strong>{result?.status ?? "—"}</strong></div>; })}{!historicalRuns.length && <span className={styles.drawerMuted}>No execution history loaded on this page.</span>}</div></section>{editingCheckId === selectedCheck.check_id && <section className={styles.drawerEdit} id="rule-edit-form"><h3>Edit rule <small className={styles.editHint}>Changes stay local until you save this rule.</small></h3><label className={styles.field}>Rule name<input value={selectedCheck.name} onChange={(event) => updateCheck(selectedCheck.check_id, { name: event.target.value })} /></label><div className={styles.drawerEditRow}><label className={styles.field}>Severity<select value={selectedCheck.severity} onChange={(event) => updateCheck(selectedCheck.check_id, { severity: event.target.value as QualityCheck["severity"] })}><option>INFO</option><option>WARNING</option><option>ERROR</option><option>CRITICAL</option></select></label><label className={styles.checkField}><input type="checkbox" checked={selectedCheck.enabled} disabled={Boolean(selectedCheck.archived)} onChange={(event) => updateCheck(selectedCheck.check_id, { enabled: event.target.checked })} /><span><strong>Enabled</strong><small>Include this rule in the approved run.</small></span></label></div><div className={styles.drawerContractEditor}>{contractEditor(selectedCheck)}</div><button className={styles.primary} disabled={busy !== null || !planDirty} onClick={saveCurrentRule}>Save this rule</button></section>}</div><footer className={styles.drawerFooter}>{mode === "manage" && <><button className={styles.secondary} onClick={() => setEditingCheckId(selectedCheck.check_id)}>{editingCheckId === selectedCheck.check_id ? "Editing rule" : "Edit rule"}</button><button className={styles.secondary} disabled={busy !== null || plan.status !== "APPROVED" || !selectedCheck.enabled || Boolean(selectedCheck.archived)} onClick={() => void mutate("runRule", { checkId: selectedCheck.check_id })}>Run rule</button><button className={styles.secondary} disabled={busy !== null} onClick={() => duplicateRule(selectedCheck)}>Duplicate</button><button className={styles.danger} disabled={busy !== null || Boolean(selectedCheck.archived)} onClick={() => archiveRule(selectedCheck)}>Archive</button></>}{mode === "review" && <button className={styles.secondary} onClick={() => setEditingCheckId(selectedCheck.check_id)}>{editingCheckId === selectedCheck.check_id ? "Editing rule" : "Edit rule"}</button>}<button className={styles.quiet} onClick={() => setSelectedCheckId(null)}>Close</button></footer></aside></div>;
  })() : null;

  return <ProjectManagementShell phase={view === "contracts" ? "rules" : "review"} navActive={view === "execution" || mode === "manage" ? "plan" : "register"} contextOnly={view === "execution" || mode === "manage"} title={view === "contracts" ? (mode === "manage" ? "Quality rules" : "Define quality rules") : "Runs & evidence"} description={view === "contracts" ? (mode === "manage" ? "Inspect and manage individual rules without changing the approved project workflow." : "Select, review, and approve deterministic checks for mapped assets.") : "Review job outcomes and manage approved schedules."} headerActions={<><span className={styles.draftBadge}>{plan?.status ?? "NO PLAN"}</span>{view === "contracts" && mode === "review" && <button className={styles.secondary} disabled={busy !== null} onClick={() => void mutate("generate")}>{busy === "generate" ? "Analyzing evidence…" : plan ? "Refresh recommendations" : "Recommend tests from evidence"}</button>}</>}>
    {notice && <div className={notice.includes("failed") || notice.includes("must") || notice.includes("cannot") ? styles.dangerStrip : styles.successStrip}>{notice}</div>}
    {view === "contracts" && <div className={styles.workspaceModeBar}><div><strong>{mode === "manage" ? "Operational rule management" : "Project rule-set review"}</strong><span>{mode === "manage" ? "Inspect and act on one rule at a time." : "Choose the approved rule set for this project."}</span></div>{planDirty && <span className={styles.unsavedBadge}>UNSAVED CHANGES</span>}</div>}
    {contractAuthoring}
    {view === "contracts" && <div className={styles.contextBar}><strong>Rules scoped to discovered mappings</strong><span>Open a rule to inspect its tables, pipeline context, lineage, and evidence.</span></div>}
    {view === "execution" && <nav className={styles.executionTabs} aria-label="Execution workspace views" role="tablist">
      <Link role="tab" aria-selected={executionTab === "run"} aria-current={executionTab === "run" ? "page" : undefined} aria-label="Run results" className={executionTab === "run" ? styles.executionTabActive : ""} href={executionHref("run")}>Run results</Link>
      <Link role="tab" aria-selected={executionTab === "history"} aria-current={executionTab === "history" ? "page" : undefined} aria-label="History" className={executionTab === "history" ? styles.executionTabActive : ""} href={executionHref("history")}>History</Link>
      <Link role="tab" aria-selected={executionTab === "schedules"} aria-current={executionTab === "schedules" ? "page" : undefined} aria-label="Schedules" className={executionTab === "schedules" ? styles.executionTabActive : ""} href={executionHref("schedules")}>Schedules</Link>
    </nav>}
    <span id="run-results" aria-hidden="true" />
    {view === "execution" && executionTab === "history" && <section className={`${styles.panel} ${styles.fullWidthHistory}`} aria-busy={initialWorkspaceLoading}><header className={styles.panelHead}><div><span className={styles.eyebrow}>HISTORY</span><h2>Run history</h2><p>Persisted quality-plan runs for the selected project and environment. Open a record without losing this scope.</p></div><span>{initialWorkspaceLoading ? "LOADING…" : `${runTotal} TOTAL`}</span></header><div className={styles.summaryList}>{initialWorkspaceLoading && <div className={styles.loadingState} role="status" aria-live="polite"><strong>Loading run history</strong><span>Reading persisted runs for this project and environment…</span><div className={styles.loadingList}><span className={styles.loadingRow} /><span className={styles.loadingRow} /></div></div>}{runs.map((run) => <div className={styles.summaryRow} key={run.run_id}><span><ScopedLink href={`/test-plan?view=execution&mode=manage&tab=history&run_id=${encodeURIComponent(run.run_id)}`}>{new Date(run.started_at).toLocaleString()}</ScopedLink><small>{run.result_count} checks · {Object.entries(run.status_counts ?? {}).map(([status, count]) => `${status}: ${count}`).join(", ") || "No result details"}</small></span><strong>{run.status}</strong></div>)}{!initialWorkspaceLoading && !runs.length && <div className={styles.summaryRow}><span>No persisted runs</span><strong>—</strong></div>}</div><div className={styles.tablePagination}><span>Page {runPage} · {runTotal} total</span><div><button disabled={busy !== null || initialWorkspaceLoading || runPage <= 1} onClick={() => void loadRunPage(runPage - 1)}>Previous</button><button disabled={busy !== null || initialWorkspaceLoading || !runHasNext} onClick={() => void loadRunPage(runPage + 1)}>Next</button></div></div></section>}
    {view === "execution" && executionTab === "schedules" && <section className={`${styles.panel} ${styles.fullWidthHistory}`} aria-busy={initialWorkspaceLoading}><header className={styles.panelHead}><div><span className={styles.eyebrow}>SCHEDULING</span><h2>Schedules</h2><p>Scheduling is separate from one-off execution. Changes still require an approved quality-plan revision.</p></div><span>{initialWorkspaceLoading ? "LOADING…" : `${schedules.length} CONFIGURED`}</span></header><section id="schedules" className={styles.schedulePanel}><div className={styles.scheduleGrid}><label className={styles.field}>Trigger<select aria-label="Schedule trigger" value={scheduleType} onChange={(event) => setScheduleType(event.target.value as "INTERVAL" | "EVENT")}><option>INTERVAL</option><option>EVENT</option></select></label>{scheduleType === "INTERVAL" ? <label className={styles.field}>Every (minutes)<input aria-label="Schedule interval minutes" type="number" min="1" value={intervalMinutes} onChange={(event) => setIntervalMinutes(Number(event.target.value))} /></label> : <label className={styles.field}>Event name<input aria-label="Schedule event name" value={eventName} onChange={(event) => setEventName(event.target.value)} /></label>}<button className={styles.secondary} disabled={busy !== null || initialWorkspaceLoading || plan?.status !== "APPROVED"} onClick={() => void mutate("createSchedule", { triggerType: scheduleType, intervalMinutes: scheduleType === "INTERVAL" ? intervalMinutes : undefined, eventName: scheduleType === "EVENT" ? eventName : undefined })}>Create schedule</button></div><div className={styles.summaryList}>{initialWorkspaceLoading && <div className={styles.loadingState} role="status" aria-live="polite"><strong>Loading schedules</strong><span>Reading persisted schedule configuration…</span><div className={styles.loadingList}><span className={styles.loadingRow} /><span className={styles.loadingRow} /></div></div>}{schedules.map((item) => <div className={styles.summaryRow} key={item.schedule_id}><span>{item.trigger_type === "INTERVAL" ? `Every ${item.interval_minutes} min` : item.event_name}<small>{item.next_run_at ? `Next ${new Date(item.next_run_at).toLocaleString()}` : "No next interval run"}</small></span><button className={styles.quiet} disabled={busy !== null} onClick={() => void mutate("toggleSchedule", { scheduleId: item.schedule_id, enabled: item.status !== "ACTIVE" })}>{item.status}</button></div>)}{!initialWorkspaceLoading && !schedules.length && <div className={styles.summaryRow}><span>No persistent schedule</span><strong>—</strong></div>}</div></section></section>}
    {(view === "contracts" || executionTab === "run") && (!plan ? <section className={styles.panel}><header className={styles.panelHead}><div><h2>{view === "execution" ? "Run results" : hasCurrentEvidence ? "No quality recommendations yet" : "No current quality plan"}</h2><p>{view === "execution" ? "No approved quality-plan run is available for this project and environment." : hasCurrentEvidence ? "Run project analysis first, then let the deterministic engine recommend tests only for evidence-supported mappings." : "This project has no current discovery evidence. Quality rules and runs will appear after a connection is tested and discovery is saved."}</p></div></header><button className={styles.primary} disabled={busy !== null || !hasCurrentEvidence} onClick={() => void mutate("generate")}>{hasCurrentEvidence ? "Recommend tests from evidence" : "Awaiting current discovery evidence"}</button></section> : <>
      <section className={styles.planMetrics}><article><span>Evidence-supported mappings</span><strong>{plan.summary.mapping_count}</strong><small>Detected source-to-target paths</small></article><article><span>Recommended quality tests</span><strong>{plan.summary.check_count}</strong><small>{plan.checks.filter((item) => item.enabled).length} currently selected</small></article><article><span>Needs your confirmation</span><strong>{plan.summary.review_required_count}</strong><small>Assumptions must be reviewed</small></article><article><span>Sources not linked to a target</span><strong>{plan.summary.unmapped_source_count}</strong><small>Excluded rather than silently guessed</small></article></section>
      {view === "contracts" ? <div className={styles.planLayout}><div className={styles.sectionStack}><section className={styles.panel}><header className={styles.panelHead}><div><h2>Source-to-target mappings</h2><p>Discovered links between source and target objects. Open a rule to inspect its evidence; this is not automatic business approval.</p></div><span>{plan.mappings.length} DETECTED</span></header><label className={styles.fieldLabel}>Rule set name<input aria-label="Rule set name" value={plan.name} onChange={(event) => setPlan((current) => current ? { ...current, name: event.target.value } : current)} /></label><div className={styles.analysisTable}><table className={styles.testTable}><thead><tr><th>Source object</th><th>Target object</th><th>Detected path</th><th>Comparison key</th><th>Evidence</th></tr></thead><tbody>{plan.mappings.map((item) => <tr key={item.mapping_id}><td className={styles.testName}><strong>{item.source_name}</strong></td><td className={styles.testName}><strong>{item.target_name}</strong></td><td>{item.path_asset_ids.length} objects</td><td><input aria-label={`Comparison key for ${item.source_name}`} value={item.key_column ?? ""} onChange={(event) => updateMappingKey(item.mapping_id, event.target.value)} /></td><td><span className={`${styles.evidence} ${styles.parsed}`}>DISCOVERED</span></td></tr>)}</tbody></table></div></section>
      <section className={styles.panel}><header className={styles.panelHead}><div><h2>Quality rules</h2><p>Find a rule quickly, then open its full definition and evidence in the detail drawer.</p></div><div className={styles.tableControls}><input aria-label="Search recommended tests" placeholder="Search rule, asset, evidence or adapter" value={checkQuery} onChange={(event) => setCheckQuery(event.target.value)} /><select aria-label="Filter recommended tests" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item}>{item}</option>)}</select><select aria-label="Filter rules by status" value={ruleFilter} onChange={(event) => setRuleFilter(event.target.value)}><option value="ALL">All statuses</option><option value="ACTIVE">Active</option><option value="NEEDS_REVIEW">Needs review</option><option value="FAILED">Failed last run</option><option value="ARCHIVED">Archived</option></select></div></header><div className={styles.ruleList} role="list" aria-label="Quality rules"><div className={styles.ruleListHeader}><span>Rule</span><span>Asset</span><span>Expectation</span><span>Approval</span><span>Latest result</span><span /></div>{pagedChecks.map((item) => { const status = ruleStatus(item, plan, latestRun); const result = latestRuleResult(item, latestRun); const approval = plan.status === "APPROVED" && !item.requires_review ? "APPROVED" : item.requires_review ? "NEEDS REVIEW" : "DRAFT"; const resultClass = result === "PASS" ? styles.ruleResultPass : result === "FAIL" || result === "ERROR" ? styles.ruleResultFail : ""; return <article className={`${styles.ruleRow} ${item.archived ? styles.archivedRule : ""}`} key={item.check_id} role="listitem"><div className={styles.ruleRowName}><input aria-label={`Use ${item.name}`} type="checkbox" checked={item.enabled} disabled={item.execution_support !== "AVAILABLE" || Boolean(item.archived)} onChange={(event) => updateCheck(item.check_id, { enabled: event.target.checked })} /><div><strong>{item.name}</strong><small>{item.category.replaceAll("_", " ")} · {item.executor ?? "Adapter required"}</small></div></div><div className={styles.ruleRowAsset} title={ruleAssetLabel(item, plan)}>{ruleAssetLabel(item, plan)}</div><div className={styles.ruleRowExpectation}><strong>{ruleExpectation(item)}</strong><small>{item.severity} severity</small></div><div><span className={`${styles.ruleStatus} ${styles[`ruleStatus${status.replaceAll("_", "")}`] ?? ""}`}>{approval}</span><small className={styles.ruleRowMeta}>{status}</small></div><div><span className={`${styles.ruleResult} ${resultClass}`}>{result}</span><small className={styles.ruleRowMeta}>{item.requires_review ? "Evidence needs review" : item.execution_support}</small></div><button className={styles.secondary} onClick={() => setSelectedCheckId(item.check_id)}>View rule</button></article>; })}{!pagedChecks.length && <div className={styles.emptyTable}>No rules match these filters.</div>}</div><div className={styles.tablePagination}><span>Showing {visibleChecks.length ? (checkPage - 1) * CHECK_PAGE_SIZE + 1 : 0}–{Math.min(checkPage * CHECK_PAGE_SIZE, visibleChecks.length)} of {visibleChecks.length}</span><div><button disabled={checkPage === 1} onClick={() => setCheckPage((current) => Math.max(1, current - 1))}>Previous</button><strong>Page {checkPage} of {checkPageCount}</strong><button disabled={checkPage === checkPageCount} onClick={() => setCheckPage((current) => Math.min(checkPageCount, current + 1))}>Next</button></div></div></section></div><aside className={styles.sideStack}><section className={styles.panel}><h3>Review and approve</h3><p className={styles.panelExplanation}>Approval applies only to this exact revision, its enabled tests, thresholds and environment. Any later edit requires a new approval.</p><div className={styles.summaryList}><div className={styles.summaryRow}><span>Status</span><strong>{plan.status}</strong></div><div className={styles.summaryRow}><span>Revision</span><strong>{plan.revision}</strong></div><div className={styles.summaryRow}><span>Enabled tests</span><strong>{plan.checks.filter((item) => item.enabled && !item.archived).length}</strong></div><div className={styles.summaryRow}><span>Approved by</span><strong>{plan.approved_by ?? "Not approved"}</strong></div></div><div className={styles.toolbar}><button className={styles.secondary} disabled={busy !== null || !planDirty} onClick={save}>Save draft</button><button className={styles.primary} disabled={busy !== null || plan.status === "APPROVED" || planDirty} onClick={() => void mutate("approve", { approvedBy: "ui-operator" })}>Review and approve revision</button></div>{planDirty && <div className={styles.dangerStrip}>Save the current edits before approving a revision.</div>}</section><details className={styles.historyPanel}><summary>Version and approval history <span>{revisions.length}</span></summary><div className={styles.summaryList}>{revisions.map((item) => <div className={styles.summaryRow} key={item.revision}><span>Revision {item.revision} · {item.event}<small>{new Date(item.recorded_at).toLocaleString()} · {item.changed_by}</small></span><strong>{item.status}</strong></div>)}{!revisions.length && <div className={styles.summaryRow}><span>No saved versions</span><strong>—</strong></div>}</div></details><div className={styles.callout}><strong>Available execution adapters</strong><p>{Object.keys(adapters).join(", ") || "No live quality adapters reported by the backend."}</p></div>{plan.unmapped.sources.length > 0 && <div className={styles.dangerStrip}><strong>{plan.unmapped.sources.length} source object(s) are not linked to a target.</strong><br />They remain outside source-to-target reconciliation until evidence or an operator-reviewed mapping connects them.</div>}</aside></div> :
      <div className={styles.planLayout} style={{ display: executionTab === "run" ? undefined : "none" }}>
        <section className={styles.panel}>
          <header className={styles.panelHead}><div><h2>Execution evidence</h2><p>Queued requests execute the exact approved revision through real read-only adapters and persist every transition.</p></div><button className={styles.primary} disabled={busy !== null || plan.status !== "APPROVED"} onClick={() => void mutate("queue", { idempotencyKey: `manual:${crypto.randomUUID()}`, maxAttempts: 1, timeoutSeconds: 3600 })}>{busy === "queue" ? "Queueing…" : "Queue approved plan"}</button></header>
          {plan.status !== "APPROVED" && <div className={styles.dangerStrip}>Review and approve the current rule-set revision before execution.</div>}
          {latestRun ? <><div className={latestRun.status === "PASS" ? styles.successStrip : styles.dangerStrip}><strong>Run {latestRun.status}</strong> · {latestRun.summary.executed} checks · {new Date(latestRun.completed_at).toLocaleString()}</div><div className={styles.analysisTable}><table className={styles.testTable}><thead><tr><th>Check</th><th>Category</th><th>Status</th><th>Evidence source</th></tr></thead><tbody>{latestRun.results.map((item) => <tr key={item.check_id}><td className={styles.testName}><strong>{item.name}</strong></td><td>{item.category}</td><td><span className={`${styles.evidence} ${item.status === "PASS" ? styles.parsed : styles.conflict}`}>{item.status}</span></td><td>{evidenceSource(item.result.source)}</td></tr>)}</tbody></table></div></> : <div className={styles.infoStrip}><span>i</span><div><strong>No execution yet</strong><p>Review and approve the quality rules, then queue the exact revision here. No success state is fabricated.</p></div></div>}
        </section>
        <aside className={styles.sideStack}>
          <div className={styles.callout}><strong>Governed automation</strong><p>Scheduler polls every {schedulerPollSeconds || "—"} seconds, allows one run per plan, deduplicates persisted trigger keys, retries recoverable failures and recovers interrupted requests after restart.</p></div>
        </aside>
      </div>}
    </>)}
    {detailsDrawer}
  </ProjectManagementShell>;
}
