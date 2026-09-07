import fs from 'node:fs';
import path from 'node:path';
import { runCommand } from '../utils/process.mjs';
import { airflowAudit, airflowStatus } from './airflow.mjs';

const SKIP_DIRS = new Set(['.git', 'node_modules', '.venv', 'venv', '__pycache__']);

function walkFiles(dir, predicate, out = [], depth = 8) {
  if (depth < 0 || !fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory() && SKIP_DIRS.has(entry.name)) continue;
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walkFiles(file, predicate, out, depth - 1);
    else if (entry.isFile() && predicate(file)) out.push(file);
  }
  return out;
}

export function findDagRoots(root) {
  const resolved = path.resolve(root);
  const candidates = [path.join(resolved, 'airflow', 'dags'), path.join(resolved, 'dags'), path.join(resolved, 'src', 'dags')];
  if (path.basename(resolved) === 'dags') candidates.unshift(resolved);
  return [...new Set(candidates.filter(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()))];
}

function stringValue(text, name) {
  return text.match(new RegExp(`${name}\\s*=\\s*["']([^"']+)["']`))?.[1] || null;
}

function booleanValue(text, name) {
  const value = text.match(new RegExp(`${name}\\s*=\\s*(True|False)`, 'i'))?.[1];
  return value ? value.toLowerCase() === 'true' : null;
}

function numberValue(text, name) {
  const value = text.match(new RegExp(`["']?${name}["']?\\s*[:=]\\s*(\\d+)`))?.[1];
  return value == null ? null : Number(value);
}

function extractTargetTables(source) {
  const tables = [];
  const pattern = /\b(?:copy\s+into|merge\s+into|insert\s+into|update|create\s+(?:or\s+replace\s+)?(?:table|view))\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*){0,2})/gi;
  for (const match of source.matchAll(pattern)) tables.push(match[1].toUpperCase());
  return [...new Set(tables)];
}

function parseTasks(source) {
  const tasks = new Map(); const variableToId = new Map();
  const taskPattern = /(?:^|\n)\s*([A-Za-z_]\w*)\s*=\s*([A-Za-z_][\w.]*(?:Operator|Sensor))\s*\(([\s\S]*?)(?=\n\s*(?:[A-Za-z_]\w*\s*=|with\s+TaskGroup|return\b|$))/g;
  for (const match of source.matchAll(taskPattern)) {
    const variable = match[1]; const body = match[3]; const taskId = stringValue(body, 'task_id') || variable;
    const connectionIds = [...body.matchAll(/\b[A-Za-z_]\w*conn_id\s*=\s*["']([^"']+)["']/gi)].map(item => item[1]);
    tasks.set(taskId, { taskId, variable, operator: match[2].split('.').at(-1), connectionIds: [...new Set(connectionIds)], targetTables: extractTargetTables(body) });
    variableToId.set(variable, taskId);
  }
  for (const match of source.matchAll(/@task(?:\([^)]*\))?\s*(?:\n\s*)?(?:async\s+)?def\s+([A-Za-z_]\w*)/g)) {
    const taskId = match[1]; if (!tasks.has(taskId)) tasks.set(taskId, { taskId, variable: taskId, operator: 'TaskFlowTask', connectionIds: [], targetTables: [] });
    variableToId.set(taskId, taskId);
  }
  const taskGroups = [];
  for (const match of source.matchAll(/with\s+TaskGroup\(\s*(?:group_id\s*=\s*)?["']([^"']+)["'][^)]*\)\s+as\s+([A-Za-z_]\w*)/g)) {
    taskGroups.push({ groupId: match[1], variable: match[2] }); variableToId.set(match[2], match[1]);
  }
  return { tasks: [...tasks.values()], taskGroups, variableToId };
}

function dependencyTokens(segment, variableToId) {
  return [...new Set([...String(segment).matchAll(/\b[A-Za-z_]\w*\b/g)].map(match => variableToId.get(match[0])).filter(Boolean))];
}

function parseEdges(source, variableToId) {
  const edges = [];
  for (const rawLine of source.split('\n')) {
    const line = rawLine.split('#')[0]; if (!line.includes('>>') && !line.includes('<<')) continue;
    const parts = line.split(/(>>|<<)/).map(part => part.trim()).filter(Boolean);
    for (let i = 1; i < parts.length - 1; i += 2) {
      const left = dependencyTokens(parts[i - 1], variableToId); const right = dependencyTokens(parts[i + 1], variableToId);
      for (const a of left) for (const b of right) edges.push(parts[i] === '>>' ? { from: a, to: b } : { from: b, to: a });
    }
  }
  for (const match of source.matchAll(/([A-Za-z_]\w*)\.set_(upstream|downstream)\(([^)]+)\)/g)) {
    const current = variableToId.get(match[1]); if (!current) continue;
    for (const other of dependencyTokens(match[3], variableToId)) edges.push(match[2] === 'upstream' ? { from: other, to: current } : { from: current, to: other });
  }
  return [...new Map(edges.map(edge => [`${edge.from}>${edge.to}`, edge])).values()];
}

function extractDagIds(source) {
  const ids = new Set();
  for (const pattern of [/dag_id\s*=\s*["']([^"']+)["']/g, /(?:with\s+)?DAG\(\s*["']([^"']+)["']/g, /@dag\([\s\S]{0,800}?dag_id\s*=\s*["']([^"']+)["']/g, /\bdbt_dag\(\s*["']([^"']+)["']/g]) {
    for (const match of source.matchAll(pattern)) ids.add(match[1]);
  }
  return [...ids];
}

function extractConnections(source) {
  const values = [];
  for (const match of source.matchAll(/\b([A-Za-z_]\w*conn_id)\s*=\s*["']([^"']+)["']/gi)) values.push({ parameter: match[1], connectionId: match[2] });
  return [...new Map(values.map(value => [value.connectionId, value])).values()];
}

function parseCatalogJobs(source, file) {
  const jobs = [];
  for (const match of source.matchAll(/\bjob\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*,([\s\S]*?)\)/g)) {
    const entityText = match[3].split(/\bstrategy\s*=/)[0];
    jobs.push({ dagId: match[1], sourceSystem: match[2], sourceEntities: [...entityText.matchAll(/["']([^"']+)["']/g)].map(item => item[1]), configuredBy: file });
  }
  return jobs;
}

function parseFile(source, file, root, syntax) {
  const parsed = parseTasks(source); const schedule = stringValue(source, 'schedule') || stringValue(source, 'schedule_interval');
  return {
    file: path.relative(root, file), dagIds: extractDagIds(source), schedule,
    hasSchedule: schedule != null || /schedule\s*=\s*None|schedule_interval\s*=\s*None/.test(source),
    catchup: booleanValue(source, 'catchup'), retries: numberValue(source, 'retries'),
    tasks: parsed.tasks, taskGroups: parsed.taskGroups, edges: parseEdges(source, parsed.variableToId),
    connections: extractConnections(source), targetTables: extractTargetTables(source),
    dbtCommands: [...new Set([...source.matchAll(/\bdbt\s+(?:build|test|run|seed|snapshot|parse|compile)\b[^"'\n]*/gi)].map(match => match[0].trim()))],
    triggerDagIds: [...new Set([...source.matchAll(/trigger_dag_id\s*=\s*["']([^"']+)["']/g)].map(match => match[1]))],
    syntaxOk: syntax.ok, syntaxError: syntax.ok ? null : (syntax.stderr || syntax.error || 'Python compile failed').trim(),
    usesDbt: /\bdbt\s+(?:build|test|run|seed|snapshot|parse|compile)\b|dbt[_-]/i.test(source),
    usesSnowflake: /Snowflake(?:Hook|Operator|SqlApi)|snowflake_[A-Za-z0-9_-]+|snowflake\.connector/i.test(source)
  };
}

function mergeDag(previous, next) {
  if (!previous) return next;
  const uniqueObjects = key => [...new Map([...(previous[key] || []), ...(next[key] || [])].map(value => [JSON.stringify(value), value])).values()];
  return { ...previous, ...next, files: [...new Set([...(previous.files || []), ...(next.files || [])])], tasks: uniqueObjects('tasks'), taskGroups: uniqueObjects('taskGroups'), edges: uniqueObjects('edges'), connections: uniqueObjects('connections'), targetTables: [...new Set([...(previous.targetTables || []), ...(next.targetTables || [])])], dbtCommands: [...new Set([...(previous.dbtCommands || []), ...(next.dbtCommands || [])])], triggerDagIds: [...new Set([...(previous.triggerDagIds || []), ...(next.triggerDagIds || [])])], sourceEntities: [...new Set([...(previous.sourceEntities || []), ...(next.sourceEntities || [])])] };
}

export function buildAirflowInventory({ cwd = process.cwd(), projectPath = '.' } = {}) {
  const root = path.resolve(cwd, projectPath || '.'); if (!fs.existsSync(root)) throw new Error(`Airflow project path not found: ${root}`);
  const roots = findDagRoots(root); const files = [...new Set(roots.flatMap(value => walkFiles(value, file => file.endsWith('.py'))))];
  const pythonBin = process.env.LDH_PYTHON_BIN || 'python3'; const fileDetails = []; const jobs = [];
  for (const file of files) {
    const source = fs.readFileSync(file, 'utf8'); const syntax = runCommand(pythonBin, ['-c', 'import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_text(), sys.argv[1], "exec")', file], { cwd: root, timeout: 20000, maxOutput: 4000 });
    const info = parseFile(source, file, root, syntax); fileDetails.push(info); jobs.push(...parseCatalogJobs(source, info.file));
  }
  const factory = fileDetails.find(info => /generated_ingestion_dags\.py$/i.test(info.file));
  const rawTargets = [...new Set(fileDetails.flatMap(info => info.targetTables).filter(table => /\.RAW\.|RAW_INGESTION/i.test(table)))];
  const dags = new Map();
  for (const info of fileDetails) for (const dagId of info.dagIds) dags.set(dagId, mergeDag(dags.get(dagId), { dagId, files: [info.file], schedule: info.schedule, catchup: info.catchup, retries: info.retries, tasks: info.tasks, taskGroups: info.taskGroups, edges: info.edges, connections: info.connections, targetTables: info.targetTables, dbtCommands: info.dbtCommands, triggerDagIds: info.triggerDagIds, sourceSystem: null, sourceEntities: [], generatedFromCatalog: false }));
  for (const job of jobs) dags.set(job.dagId, mergeDag(dags.get(job.dagId), { dagId: job.dagId, files: [job.configuredBy, ...(factory ? [factory.file] : [])], schedule: factory?.schedule || null, catchup: factory?.catchup ?? null, retries: factory?.retries ?? null, tasks: factory?.tasks || [], taskGroups: factory?.taskGroups || [], edges: factory?.edges || [], connections: factory?.connections || [], targetTables: rawTargets, dbtCommands: [], triggerDagIds: [], sourceSystem: job.sourceSystem, sourceEntities: job.sourceEntities, generatedFromCatalog: true }));
  const dagList = [...dags.values()].sort((a, b) => a.dagId.localeCompare(b.dagId)); const issues = [];
  for (const info of fileDetails) if (!info.syntaxOk) issues.push({ severity: 'ERROR', file: info.file, message: info.syntaxError });
  for (const dag of dagList) {
    if (dag.catchup !== false) issues.push({ severity: 'WARN', dagId: dag.dagId, message: 'catchup=False not detected' });
    if (dag.schedule == null && !dag.files.some(file => fileDetails.find(item => item.file === file)?.hasSchedule)) issues.push({ severity: 'WARN', dagId: dag.dagId, message: 'schedule not detected' });
  }
  return { ok: files.length > 0 && !issues.some(issue => issue.severity === 'ERROR'), summary: files.length ? `${dagList.length} Airflow DAG(s) from ${files.length} Python file(s); ${issues.length} issue(s).` : 'No Airflow DAG files found.', root, roots: roots.map(value => path.relative(root, value) || '.'), fileCount: files.length, dagCount: dagList.length, taskCount: dagList.reduce((sum, dag) => sum + dag.tasks.length, 0), files: fileDetails, dags: dagList, issues, integration: { dbt: fileDetails.some(item => item.usesDbt), snowflake: fileDetails.some(item => item.usesSnowflake) } };
}

function inventory(args, cwd) { return buildAirflowInventory({ cwd, projectPath: args?.projectPath || '.' }); }
function resolveDag(value, dagId) { const dag = value.dags.find(item => item.dagId === dagId); if (!dag) throw new Error(`Airflow DAG not found: ${dagId}`); return dag; }

export const airflowInventory = {
  name: 'airflow_inventory', description: 'Return calculated Airflow DAG, task, source, target, connection, and dbt-command inventory.',
  parameters: { type: 'object', properties: { projectPath: { type: 'string' }, targetTable: { type: 'string' } } },
  async execute(args = {}, { cwd }) { const value = inventory(args, cwd); const target = args.targetTable?.toUpperCase(); if (!target) return value; const dags = value.dags.filter(dag => dag.targetTables.some(table => table === target || table.endsWith(`.${target}`) || target.endsWith(`.${table}`))); return { ...value, summary: `${dags.length} DAG(s) write ${target}.`, dags, dagCount: dags.length }; }
};

export const airflowDagDetails = {
  name: 'airflow_dag_details', description: 'Return deterministic static details for one Airflow DAG.',
  parameters: { type: 'object', required: ['dagId'], properties: { projectPath: { type: 'string' }, dagId: { type: 'string' } } },
  async execute(args, { cwd }) { const dag = resolveDag(inventory(args, cwd), args.dagId); return { ok: true, summary: `${dag.dagId}: ${dag.tasks.length} task(s), ${dag.edges.length} edge(s).`, dag }; }
};

export const airflowTaskGraph = {
  name: 'airflow_task_graph', description: 'Return task nodes and dependency edges for one Airflow DAG.',
  parameters: { type: 'object', required: ['dagId'], properties: { projectPath: { type: 'string' }, dagId: { type: 'string' } } },
  async execute(args, { cwd }) { const dag = resolveDag(inventory(args, cwd), args.dagId); return { ok: true, summary: `${dag.tasks.length} task(s), ${dag.edges.length} edge(s) in ${dag.dagId}.`, dagId: dag.dagId, tasks: dag.tasks, taskGroups: dag.taskGroups, edges: dag.edges }; }
};

export const airflowDependencies = {
  name: 'airflow_dependencies', description: 'Return upstream/downstream task dependencies or triggered DAG dependencies.',
  parameters: { type: 'object', required: ['dagId'], properties: { projectPath: { type: 'string' }, dagId: { type: 'string' }, taskId: { type: 'string' }, depth: { type: 'integer', minimum: 1, maximum: 100 } } },
  async execute(args, { cwd }) {
    const dag = resolveDag(inventory(args, cwd), args.dagId); if (!args.taskId) return { ok: true, summary: `${dag.triggerDagIds.length} triggered DAG dependency/dependencies.`, dagId: dag.dagId, triggers: dag.triggerDagIds };
    const ids = new Set([...dag.tasks.map(task => task.taskId), ...dag.taskGroups.map(group => group.groupId)]); if (!ids.has(args.taskId)) throw new Error(`Task not found in ${dag.dagId}: ${args.taskId}`);
    const depth = Number(args.depth) || 25; const traverse = direction => { const seen = new Set([args.taskId]); const queue = [{ id: args.taskId, level: 0 }]; const found = []; while (queue.length) { const current = queue.shift(); if (current.level >= depth) continue; const adjacent = dag.edges.filter(edge => direction === 'upstream' ? edge.to === current.id : edge.from === current.id).map(edge => direction === 'upstream' ? edge.from : edge.to); for (const id of adjacent) if (!seen.has(id)) { seen.add(id); found.push({ taskId: id, depth: current.level + 1 }); queue.push({ id, level: current.level + 1 }); } } return found; };
    const upstream = traverse('upstream'); const downstream = traverse('downstream'); return { ok: true, summary: `${upstream.length} upstream and ${downstream.length} downstream task dependency/dependencies.`, dagId: dag.dagId, taskId: args.taskId, upstream, downstream };
  }
};

export const airflowConnectionsUsed = {
  name: 'airflow_connections_used', description: 'Inventory Airflow connection IDs without reading credential values.',
  parameters: { type: 'object', properties: { projectPath: { type: 'string' }, dagId: { type: 'string' } } },
  async execute(args = {}, { cwd }) { const value = inventory(args, cwd); const dags = args.dagId ? [resolveDag(value, args.dagId)] : value.dags; const connectionIds = [...new Set(dags.flatMap(dag => dag.connections.map(item => item.connectionId)))]; return { ok: true, summary: `${connectionIds.length} Airflow connection ID(s) detected.`, connectionIds, dags: dags.map(dag => ({ dagId: dag.dagId, connections: dag.connections })) }; }
};

export const airflowHealth = {
  name: 'airflow_health', description: 'Combine Airflow static validation with an optional read-only CLI health check.',
  parameters: { type: 'object', properties: { projectPath: { type: 'string' }, live: { type: 'boolean' } } },
  async execute(args = {}, { cwd }) { const value = inventory(args, cwd); let live = { status: 'SKIP', summary: 'Live Airflow check not requested.' }; if (args.live) { const result = await airflowStatus.execute({}, { cwd: path.resolve(cwd, args.projectPath || '.') }); live = { status: result.available === false ? 'SKIP' : result.ok ? 'PASS' : 'FAIL', ...result }; } return { ok: value.ok && live.status !== 'FAIL', summary: `Airflow static=${value.ok ? 'PASS' : 'FAIL'} live=${live.status}.`, static: value, live }; }
};

export const airflowFailureSummary = {
  name: 'airflow_failure_summary', description: 'Summarize explicit ERROR/FAILED records from local Airflow logs; SKIP when logs are absent.',
  parameters: { type: 'object', properties: { projectPath: { type: 'string' }, maxFiles: { type: 'integer', minimum: 1, maximum: 500 } } },
  async execute(args = {}, { cwd }) { const root = path.resolve(cwd, args.projectPath || '.'); const logRoots = [path.join(root, 'airflow', 'logs'), path.join(root, 'logs')].filter(fs.existsSync); const files = logRoots.flatMap(dir => walkFiles(dir, file => /\.(log|txt)$/i.test(file))).slice(-(Number(args.maxFiles) || 100)); if (!files.length) return { ok: true, status: 'SKIP', summary: 'No local Airflow task logs found.', failures: [] }; const failures = []; for (const file of files) { const lines = fs.readFileSync(file, 'utf8').split('\n').filter(line => /\b(ERROR|FAILED|Traceback)\b/.test(line)); if (lines.length) failures.push({ file: path.relative(root, file), count: lines.length, samples: lines.slice(-5).map(line => line.slice(0, 1000)) }); } return { ok: failures.length === 0, status: failures.length ? 'FAIL' : 'PASS', summary: `${failures.reduce((sum, item) => sum + item.count, 0)} failure/error line(s) across ${files.length} log file(s).`, failures }; }
};

export const airflowIntelligenceTools = [airflowInventory, airflowDagDetails, airflowTaskGraph, airflowDependencies, airflowConnectionsUsed, airflowHealth, airflowFailureSummary];

// Compatibility helper for callers that want both the original v0.2 audit and richer inventory.
export async function combinedAirflowAudit(args, context) {
  const [audit, rich] = await Promise.all([airflowAudit.execute(args, context), airflowInventory.execute(args, context)]);
  return { audit, inventory: rich };
}
