import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (path: string) => readFile(new URL(path, import.meta.url), "utf8");

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
});

test("Ask AI keeps the concise answer primary and makes evidence and technical output expandable", async () => {
  const page = await source("../app/agent/page.tsx");

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
  assert.match(page, /Evidence connector failed/);
  assert.match(page, /AI returned no usable answer/);
  assert.match(page, /AI explanation completed\./);
  assert.match(page, /const liveExplanation = agentOutcome === "LIVE_RESPONSE" && Boolean\(modelAnswer\);/);
  assert.match(page, /const directAnswer = liveExplanation \? "" : modelAnswer;/);
  assert.match(page, /const headline = executionRequest/);
  assert.match(page, /: directAnswer\n\s+\? "Evidence collected\."/);
  assert.match(page, /result\.request_type === "execution"/);
  assert.match(page, /const requiresQualityScope = responseResult\.quality_scope === "REQUIRED";/);
  assert.match(page, /humanStatus\(requiresQualityScope \? responseResult\.status/);
  assert.match(page, /LIVE_RESPONSE" && response\.answer/);
  assert.doesNotMatch(page, /compactNarrative\(response\.question/);
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
