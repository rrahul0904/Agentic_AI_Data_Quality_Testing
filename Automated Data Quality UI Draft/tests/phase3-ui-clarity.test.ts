import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { sourceTableDiscoveryCoverage } from "../lib/catalog-coverage.ts";

const source = (path: string) => readFile(new URL(path, import.meta.url), "utf8");

test("Run Jobs separates dbt model selection from quality checks", async () => {
  const page = await source("../app/actions/page.tsx");
  assert.match(page, /value: "dbt_execute", label: "dbt model", prefix: "Run only this dbt model: "/);
  assert.match(page, /value: "quality_checks", label: "Quality checks \/ dbt tests"/);
  assert.doesNotMatch(page, /label: "dbt model or test"/);
});

test("Connections keep a readable table at laptop widths and use a compact layout only on phones", async () => {
  const page = await source("../app/register-project/page.tsx");
  const css = await source("../app/register-project/onboarding.module.css");

  assert.match(page, /data-label="Connection check"/);
  assert.match(page, /connectionStatusLabel/);
  assert.match(page, /Connected/);
  assert.match(page, /role="region" aria-label="Configured connections\. Scroll to view all connection actions\."/);
  assert.match(css, /\.connectionTable \{ width: 100%; min-width: 1040px;/);
  assert.match(css, /@media \(max-width: 720px\)/);
  assert.doesNotMatch(css, /@container \(max-width: 1120px\) \{\s*\.connectionTable/);
  assert.match(css, /scrollbar-gutter: stable both-edges/);
});

test("Monitoring keeps the table concise and presents run details in a keyboard-closeable dialog", async () => {
  const page = await source("../app/monitoring/page.tsx");

  assert.match(page, /<th>Job \/ asset<\/th><th>Execution<\/th><th>Verification<\/th><th>Last checked<\/th>/);
  assert.doesNotMatch(page, /<th>Submission<\/th><th>Execution<\/th><th>Verification<\/th><th>Data quality<\/th>/);
  assert.match(page, /role="dialog" aria-modal="true" aria-labelledby="selected-run-title"/);
  assert.match(page, /event\.key === "Escape"/);
  assert.match(page, /detailOpener\.current\?\.focus\(\)/);
  assert.match(page, /Open this run&apos;s evidence/);
  assert.match(page, /Worker check history/);
  assert.match(page, /Submission: \{statusLabel/);
  assert.match(page, /External runtime: \{statusLabel/);
});

test("an approved quality plan still allows a new mapped draft rule", async () => {
  const page = await source("../app/test-plan/page.tsx");

  assert.match(page, /addChecks: \[\{ mapping_id: mapping\.mapping_id, name: `\$\{newContractType\} \$\{selected\}`/);
  assert.match(page, /Saving creates a new draft revision and ends the current approval/);
  assert.match(page, /disabled=\{busy !== null\} onClick=\{addContract\}>Create draft rule/);
  assert.doesNotMatch(page, /disabled=\{busy !== null \|\| plan\.status === "APPROVED"\} onClick=\{addContract\}/);
});

test("Ask AI keeps the concise answer primary and makes evidence and technical output expandable", async () => {
  const page = await source("../app/agent/page.tsx");
  const css = await source("../app/agent/agent.module.css");

  assert.match(page, /Ask about the selected project, asset, or run\. Answers cite only the scope below\./);
  assert.match(page, /const \[question, setQuestion\] = useState\(""\);/);
  assert.match(page, /Ask AI history/);
  assert.match(page, /history_limit=20&history_offset=/);
  assert.match(page, /historyLayout/);
  assert.match(page, /historyDetail/);
  assert.match(page, /historyPager/);
  assert.match(page, /Page \{page\}/);
  assert.match(page, /onPrevious/);
  assert.match(page, /onNext/);
  assert.match(page, /usageLabel\(item\.usage\)/);
  assert.match(page, /agent_history/);
  assert.match(page, /Open response:/);
  assert.match(page, /onDoubleClick/);
  assert.match(page, /href="#ask-ai-history-detail-heading"/);
  assert.match(page, /aria-current=\{selectedId === itemId \? "true" : undefined\}/);
  assert.doesNotMatch(page, /aria-pressed=\{selectedId === itemId\}/);
  assert.match(page, /ask-ai-history-detail-heading/);
  assert.match(page, /historyViewer/);
  assert.match(page, /Evidence and tools/);
  assert.match(page, /placeholder="Ask a question about this project, selected asset, or run"/);
  assert.doesNotMatch(page, /What is the current quality status and which evidence supports it\?/);
  assert.match(page, /<summary>Evidence and supporting records/);
  assert.match(page, /<summary>Technical details<\/summary>/);
  assert.match(page, /aria-live="polite"/);
  assert.match(page, /role="alert"/);
  assert.match(page, /This is an execution request, not an explanation request\./);
  assert.match(page, /AI stopped at the evidence-query limit/);
  assert.match(page, /AI provider timed out/);
  assert.match(page, /LIVE_PROVIDER_HTTP_400/);
  assert.match(page, /LIVE_PROVIDER_HTTP_429/);
  assert.match(page, /Evidence connector failed/);
  assert.match(page, /AI returned no usable answer/);
  assert.match(page, /const liveExplanation = agentOutcome === "LIVE_RESPONSE" && Boolean\(modelAnswer\);/);
  assert.match(page, /const directAnswer = liveExplanation \? "" : modelAnswer;/);
  assert.match(page, /const headline = executionRequest/);
  assert.match(page, /const liveAnswerParts = liveExplanation \? splitLiveAnswer\(modelAnswer\) : null;/);
  assert.match(page, /: liveExplanation\n\s+\? liveAnswerParts!\.headline/);
  assert.match(page, /: liveExplanation\n\s+\? liveAnswerParts!\.detail/);
  assert.match(page, /<FormattedAnswer text=\{item\.answer \|\|/);
  assert.match(page, /<FormattedAnswer text=\{readable\.detail\} \/>/);
  assert.match(page, /function FormattedAnswer\(/);
  assert.match(page, /Saved at \{formatDateTime\(item\.created_at\)\}/);
  assert.match(page, /\{items\.length\} shown · \{savedResults\.length\} with results/);
  assert.match(page, /window\.matchMedia\("\(max-width: 980px\)"\)\.matches/);
  assert.match(page, /scrollIntoView\(\{/);
  assert.match(page, /<details className=\{local\.historyEvidenceDetails\}>/);
  assert.match(css, /\.historyViewer \{[^}]*max-width: 100%/);
  assert.match(css, /\.historyViewerHeader \{[^}]*flex-direction: column/);
  assert.match(css, /\.historyViewerGrid \{[^}]*grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(page, /readable\.detail \? <div className=\{local\.answerNarrative\}><FormattedAnswer text=\{readable\.detail\} \/><\/div>/);
  assert.match(page, /What’s still unknown/);
  assert.match(page, /What to check next/);
  assert.doesNotMatch(page, /compactNarrative\(modelAnswer/);
  assert.match(page, /: directAnswer\n\s+\? "Evidence collected\."/);
  assert.match(page, /result\.request_type === "execution"/);
  assert.match(page, /const requiresQualityScope = responseResult\.quality_scope === "REQUIRED";/);
  assert.match(page, /humanStatus\(requiresQualityScope \? responseResult\.status/);
  assert.doesNotMatch(page, /compactNarrative\(response\.question/);
});

test("demo readiness names the scoped model, key state, provider verification, and separate Ask AI answer state", async () => {
  const page = await source("../app/actions/page.tsx");
  assert.match(page, /verification_status\?: string/);
  assert.match(page, /item\.provider \?\? "Provider not configured"/);
  assert.match(page, /item\.model \?\? "Model not configured"/);
  assert.match(page, /item\.credential_present \? "available" : "not available"/);
  assert.match(page, /Provider verification is separate from receiving an Ask AI answer\./);
});

test("Run jobs preserves an explicitly chosen candidate and clears stale plan feedback when scope changes", async () => {
  const page = await source("../app/actions/page.tsx");

  assert.match(page, /const resetPlanDraft = \(\) =>/);
  assert.match(page, /requestedTarget: item\.name, mode, operationKind/);
  assert.match(page, /setOperationTarget\(item\.name\); setIntent\(nextIntent\)/);
  assert.match(page, /resetPlanDraft\(\); setMode\(event\.target\.value as ExecutionMode\)/);
});

test("Lineage keeps its graph before the secondary analysis details without changing existing page logic", async () => {
  const css = await source("../app/project-design/project-design.module.css");
  assert.match(css, /\.contextFrame \.managementMain > \.analysisDetails \{ order: 8; \}/);
});

test("Lineage Definition inspector distinguishes provider DDL, reconstructed DDL, source files, and unavailable states", async () => {
  const page = await source("../app/project-design/page.tsx");
  assert.match(page, /definition_kind\?: string/);
  assert.match(page, /Definition reconstructed from provider catalog metadata/);
  assert.match(page, /Exact object definition/);
  assert.match(page, /Live definition could not be confirmed/);
  assert.match(page, /Definition unavailable/);
  assert.doesNotMatch(page, /No repository source or deployed definition is attached to this asset\./);
});

test("Catalog reports selected tables missing accepted discovery instead of implying the catalog is complete", async () => {
  const page = await source("../app/project-design/page.tsx");
  assert.match(page, /Discovery covers \{sourceCoverage\.discovered\} of \{uniqueSavedSourceTables\.length\} selected source tables/);
  assert.match(page, /Filter pipeline layer/);
  assert.match(page, /Review discovery/);
  assert.match(page, /The last saved catalog remains on screen; no new analysis result was saved/);

  const tables = ["one", "two", "three"].map((id) => ({ id, table: id, database: "db", schema: "public", columns: [] }));
  const nodes = [
    { node_id: "source-one", kind: "source_table", name: "one", properties: { source_table_id: "one" } },
    { node_id: "source-two", kind: "source_table", name: "two", properties: { source_table_id: "two" } },
    { node_id: "model-three", kind: "dbt_model", name: "three", properties: { source_table_id: "three" } },
  ] as never[];
  const coverage = sourceTableDiscoveryCoverage(tables, nodes);
  assert.equal(coverage.discovered, 2);
  assert.deepEqual(coverage.missing.map((item) => item.id), ["three"]);
});

test("direct Lineage route keeps full-catalog scope when analysis finishes after navigation", async () => {
  const page = await source("../app/project-design/page.tsx");
  assert.match(page, /window\.location\.pathname === "\/map-flows"/);
  assert.match(page, /setPipelineId\(view === "map" \|\| isMapRoute\(\) \? ALL_ACCEPTED_FLOWS_ID/);
  assert.match(page, /const \[analysisLoading, setAnalysisLoading\] = useState\(true\)/);
  assert.match(page, /disabled=\{busy \|\| analysisLoading\}/);
});
