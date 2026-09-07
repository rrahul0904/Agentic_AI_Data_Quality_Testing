import fs from 'node:fs';
import path from 'node:path';

const SKIP_DIRS = new Set(['.git', 'node_modules', 'logs', '.venv', 'venv', '__pycache__']);
const ARTIFACT_NAMES = ['manifest.json', 'catalog.json', 'run_results.json', 'sources.json'];

function walkFor(root, fileName, out = [], depth = 8) {
  if (depth < 0 || !fs.existsSync(root)) return out;
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.isDirectory() && SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) walkFor(full, fileName, out, depth - 1);
    else if (entry.isFile() && entry.name === fileName) out.push(full);
  }
  return out;
}

function readJson(file) {
  if (!file || !fs.existsSync(file)) return null;
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (error) { throw new Error(`Invalid dbt artifact ${file}: ${error.message}`); }
}

function artifactCandidate(projectDir, name, explicitPath) {
  if (explicitPath) return path.resolve(projectDir, explicitPath);
  const preferred = [path.join(projectDir, 'target', name), path.join(projectDir, 'dbt', name)];
  for (const file of preferred) if (fs.existsSync(file)) return file;
  if (name === 'manifest.json') {
    for (const file of walkFor(projectDir, name)) {
      try {
        const value = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (value && (value.nodes || value.sources || value.exposures)) return file;
      } catch { /* the loader reports an error only for the selected artifact */ }
    }
    return null;
  }
  return walkFor(projectDir, name)[0] || null;
}

export function findDbtProjectDir(root) {
  const resolved = path.resolve(root);
  if (fs.existsSync(path.join(resolved, 'dbt_project.yml'))) return resolved;
  const project = walkFor(resolved, 'dbt_project.yml')[0];
  return project ? path.dirname(project) : resolved;
}

function relativeOrAbsolute(root, file) {
  if (!file) return null;
  const relative = path.relative(root, file);
  return relative.startsWith('..') ? file : (relative || '.');
}

function resultStatusIndex(runResults) {
  return Object.fromEntries((runResults?.results || []).map(result => [result.unique_id, {
    status: result.status || null,
    executionTime: result.execution_time ?? null,
    message: result.message || null,
    failures: result.failures ?? null
  }]));
}

function catalogIndex(catalog) {
  return { ...(catalog?.sources || {}), ...(catalog?.nodes || {}) };
}

function freshnessIndex(sourcesArtifact) {
  return Object.fromEntries((sourcesArtifact?.results || []).map(result => [result.unique_id, {
    status: result.status || null,
    maxLoadedAt: result.max_loaded_at || null,
    snapshottedAt: result.snapshotted_at || null,
    age: result.age ?? null,
    criteria: result.criteria || null
  }]));
}

function normalizedNode(uniqueId, raw, runStatus, catalog, freshness) {
  const resourceType = raw.resource_type || uniqueId.split('.')[0] || 'unknown';
  return {
    uniqueId,
    name: raw.name || uniqueId.split('.').at(-1),
    resourceType,
    packageName: raw.package_name || uniqueId.split('.')[1] || null,
    path: raw.original_file_path || raw.path || null,
    database: raw.database || null,
    schema: raw.schema || null,
    alias: raw.alias || raw.identifier || null,
    relationName: raw.relation_name || null,
    description: raw.description || null,
    tags: raw.tags || [],
    config: raw.config ? {
      enabled: raw.config.enabled,
      materialized: raw.config.materialized,
      schema: raw.config.schema || null
    } : null,
    dependsOn: [...new Set(raw.depends_on?.nodes || [])],
    columns: catalog?.columns || raw.columns || {},
    stats: catalog?.stats || {},
    status: runStatus || null,
    freshness: freshness || null,
    checksum: raw.checksum?.checksum || null
  };
}

function publicNode(node) {
  if (!node) return null;
  return { ...node, dependsOn: [...node.dependsOn] };
}

function descendants(graph, startId, direction, depth = 25) {
  const adjacency = direction === 'upstream' ? graph.parents : graph.children;
  const queue = (adjacency[startId] || []).map(id => ({ id, level: 1 }));
  const seen = new Set([startId]);
  const items = [];
  const edges = [];
  while (queue.length) {
    const current = queue.shift();
    if (seen.has(current.id) || current.level > depth) continue;
    seen.add(current.id);
    if (graph.nodes[current.id]) items.push({ ...publicNode(graph.nodes[current.id]), depth: current.level });
    edges.push(direction === 'upstream'
      ? { from: current.id, to: current.level === 1 ? startId : null, type: 'depends_on' }
      : { from: current.level === 1 ? startId : null, to: current.id, type: 'depends_on' });
    for (const id of adjacency[current.id] || []) queue.push({ id, level: current.level + 1 });
  }
  return { items, ids: items.map(item => item.uniqueId), edges };
}

export function resolveDbtNode(graph, selector) {
  if (!selector) throw new Error('node is required');
  if (graph.nodes[selector]) return selector;
  const normalized = String(selector).replace(/^dbt[.:]/i, '').toLowerCase();
  const candidates = Object.values(graph.nodes).filter(node => {
    const values = [node.uniqueId, node.name, node.alias, node.relationName].filter(Boolean).map(String);
    return values.some(value => value.toLowerCase() === normalized || value.toLowerCase().endsWith(`.${normalized}`));
  });
  if (!candidates.length) throw new Error(`dbt node not found: ${selector}`);
  if (candidates.length > 1) throw new Error(`Ambiguous dbt node '${selector}': ${candidates.map(node => node.uniqueId).join(', ')}`);
  return candidates[0].uniqueId;
}

export function loadDbtGraph({ cwd = process.cwd(), projectPath = '.', manifestPath, catalogPath, runResultsPath, sourcesPath } = {}) {
  const requestedRoot = path.resolve(cwd, projectPath || '.');
  if (!fs.existsSync(requestedRoot) || !fs.statSync(requestedRoot).isDirectory()) throw new Error(`Project directory not found: ${requestedRoot}`);
  const projectDir = findDbtProjectDir(requestedRoot);
  const files = {
    manifest: artifactCandidate(projectDir, 'manifest.json', manifestPath),
    catalog: artifactCandidate(projectDir, 'catalog.json', catalogPath),
    runResults: artifactCandidate(projectDir, 'run_results.json', runResultsPath),
    sources: artifactCandidate(projectDir, 'sources.json', sourcesPath)
  };
  if (!files.manifest) throw new Error(`dbt manifest.json not found under ${projectDir}`);
  const manifest = readJson(files.manifest);
  const catalog = readJson(files.catalog);
  const runResults = readJson(files.runResults);
  const sourcesArtifact = readJson(files.sources);
  const statuses = resultStatusIndex(runResults);
  const catalogNodes = catalogIndex(catalog);
  const freshness = freshnessIndex(sourcesArtifact);
  const rawNodes = {
    ...(manifest.sources || {}),
    ...(manifest.nodes || {}),
    ...(manifest.exposures || {}),
    ...(manifest.metrics || {})
  };
  const nodes = {};
  for (const [uniqueId, raw] of Object.entries(rawNodes)) {
    nodes[uniqueId] = normalizedNode(uniqueId, raw, statuses[uniqueId], catalogNodes[uniqueId], freshness[uniqueId]);
  }
  const parents = Object.fromEntries(Object.keys(nodes).map(id => [id, []]));
  const children = Object.fromEntries(Object.keys(nodes).map(id => [id, []]));
  for (const node of Object.values(nodes)) {
    parents[node.uniqueId] = node.dependsOn.filter(id => nodes[id]);
    for (const parent of parents[node.uniqueId]) children[parent].push(node.uniqueId);
  }
  for (const value of Object.values(children)) value.sort();
  const testsByNode = {};
  const exposuresByNode = {};
  for (const node of Object.values(nodes)) {
    if (node.resourceType === 'test') {
      for (const parent of parents[node.uniqueId]) (testsByNode[parent] ||= []).push(node.uniqueId);
    }
    if (node.resourceType === 'exposure') {
      for (const parent of parents[node.uniqueId]) (exposuresByNode[parent] ||= []).push(node.uniqueId);
    }
  }
  const graph = {
    projectDir,
    artifacts: Object.fromEntries(Object.entries(files).map(([key, value]) => [key, relativeOrAbsolute(projectDir, value)])),
    metadata: manifest.metadata || {},
    nodes,
    parents,
    children,
    testsByNode,
    exposuresByNode,
    sourcesByModel: {}
  };
  for (const node of Object.values(nodes)) {
    if (node.resourceType !== 'model') continue;
    graph.sourcesByModel[node.uniqueId] = descendants(graph, node.uniqueId, 'upstream', 100).items
      .filter(item => item.resourceType === 'source').map(item => item.uniqueId);
  }
  return graph;
}

function loadFromTool(args, cwd) {
  return loadDbtGraph({ cwd, ...args });
}

function traversalResult(graph, selector, direction, depth) {
  const id = resolveDbtNode(graph, selector);
  const result = descendants(graph, id, direction, Math.max(1, Math.min(100, Number(depth) || 25)));
  return {
    ok: true,
    summary: `${result.items.length} ${direction} dbt node(s) found for ${graph.nodes[id].name}.`,
    node: publicNode(graph.nodes[id]),
    direction,
    depth: Number(depth) || 25,
    nodes: result.items
  };
}

const projectProperties = {
  projectPath: { type: 'string' }, manifestPath: { type: 'string' }, catalogPath: { type: 'string' },
  runResultsPath: { type: 'string' }, sourcesPath: { type: 'string' }
};

export const dbtManifestSummary = {
  name: 'dbt_manifest_summary', description: 'Load dbt artifacts and return deterministic resource, status, and graph counts.',
  parameters: { type: 'object', properties: projectProperties },
  async execute(args = {}, { cwd }) {
    const graph = loadFromTool(args, cwd);
    const byType = {};
    const byStatus = {};
    let edgeCount = 0;
    for (const node of Object.values(graph.nodes)) {
      byType[node.resourceType] = (byType[node.resourceType] || 0) + 1;
      if (node.status?.status) byStatus[node.status.status] = (byStatus[node.status.status] || 0) + 1;
      edgeCount += graph.parents[node.uniqueId].length;
    }
    return { ok: true, summary: `${Object.keys(graph.nodes).length} dbt node(s), ${edgeCount} dependency edge(s).`, projectDir: graph.projectDir, artifacts: graph.artifacts, dbtMetadata: graph.metadata, counts: { total: Object.keys(graph.nodes).length, edges: edgeCount, byType, byStatus } };
  }
};

export const dbtNode = {
  name: 'dbt_node', description: 'Return one dbt node with direct parents, children, tests, catalog, and latest run status.',
  parameters: { type: 'object', required: ['node'], properties: { ...projectProperties, node: { type: 'string' } } },
  async execute(args, { cwd }) {
    const graph = loadFromTool(args, cwd); const id = resolveDbtNode(graph, args.node);
    return { ok: true, summary: `dbt ${graph.nodes[id].resourceType} ${graph.nodes[id].name}.`, node: publicNode(graph.nodes[id]), parents: graph.parents[id].map(x => publicNode(graph.nodes[x])), children: graph.children[id].map(x => publicNode(graph.nodes[x])), tests: (graph.testsByNode[id] || []).map(x => publicNode(graph.nodes[x])), exposures: (graph.exposuresByNode[id] || []).map(x => publicNode(graph.nodes[x])) };
  }
};

export const dbtUpstream = {
  name: 'dbt_upstream', description: 'Traverse deterministic dbt manifest dependencies upstream with a bounded depth.',
  parameters: { type: 'object', required: ['node'], properties: { ...projectProperties, node: { type: 'string' }, depth: { type: 'integer', minimum: 1, maximum: 100 } } },
  async execute(args, { cwd }) { return traversalResult(loadFromTool(args, cwd), args.node, 'upstream', args.depth); }
};

export const dbtDownstream = {
  name: 'dbt_downstream', description: 'Traverse deterministic dbt manifest dependencies downstream with a bounded depth.',
  parameters: { type: 'object', required: ['node'], properties: { ...projectProperties, node: { type: 'string' }, depth: { type: 'integer', minimum: 1, maximum: 100 } } },
  async execute(args, { cwd }) { return traversalResult(loadFromTool(args, cwd), args.node, 'downstream', args.depth); }
};

export const dbtLineage = {
  name: 'dbt_lineage', description: 'Return the calculated upstream and downstream lineage subgraph for a dbt node.',
  parameters: { type: 'object', required: ['node'], properties: { ...projectProperties, node: { type: 'string' }, depth: { type: 'integer', minimum: 1, maximum: 100 } } },
  async execute(args, { cwd }) {
    const graph = loadFromTool(args, cwd); const id = resolveDbtNode(graph, args.node); const depth = Number(args.depth) || 25;
    const upstream = descendants(graph, id, 'upstream', depth); const downstream = descendants(graph, id, 'downstream', depth);
    const included = new Set([id, ...upstream.ids, ...downstream.ids]); const edges = [];
    for (const child of included) for (const parent of graph.parents[child] || []) if (included.has(parent)) edges.push({ from: parent, to: child, type: graph.nodes[child].resourceType === 'test' ? 'tests' : 'depends_on' });
    return { ok: true, summary: `${upstream.items.length} upstream and ${downstream.items.length} downstream node(s) for ${graph.nodes[id].name}.`, focus: publicNode(graph.nodes[id]), upstream: upstream.items, downstream: downstream.items, edges };
  }
};

export const dbtImpact = {
  name: 'dbt_impact', description: 'Calculate direct/transitive dbt impact, affected facts/marts/tests, and a dbt selector.',
  parameters: { type: 'object', required: ['node'], properties: { ...projectProperties, node: { type: 'string' }, depth: { type: 'integer', minimum: 1, maximum: 100 } } },
  async execute(args, { cwd }) {
    const graph = loadFromTool(args, cwd); const id = resolveDbtNode(graph, args.node); const result = descendants(graph, id, 'downstream', Number(args.depth) || 100);
    const direct = graph.children[id].map(x => publicNode(graph.nodes[x]));
    const facts = result.items.filter(node => /^fact_/i.test(node.name));
    const marts = result.items.filter(node => /^mart_/i.test(node.name) || /(^|\/)marts?\//i.test(node.path || ''));
    const tests = result.items.filter(node => node.resourceType === 'test');
    const exposures = result.items.filter(node => node.resourceType === 'exposure');
    const severity = marts.length || exposures.length ? 'HIGH' : facts.length ? 'MEDIUM' : result.items.length ? 'LOW' : 'NONE';
    return { ok: true, summary: `${direct.length} direct and ${result.items.length} transitive downstream node(s); severity=${severity}.`, changed: publicNode(graph.nodes[id]), directDownstream: direct, transitiveDownstream: result.items, affectedFacts: facts, affectedMarts: marts, affectedTests: tests, affectedExposures: exposures, severity, recommendedSelector: `${graph.nodes[id].name}+` };
  }
};

export const dbtTestsForNode = {
  name: 'dbt_tests_for_node', description: 'List manifest tests protecting a selected dbt node.',
  parameters: { type: 'object', required: ['node'], properties: { ...projectProperties, node: { type: 'string' } } },
  async execute(args, { cwd }) {
    const graph = loadFromTool(args, cwd); const id = resolveDbtNode(graph, args.node); const tests = (graph.testsByNode[id] || []).map(x => publicNode(graph.nodes[x]));
    return { ok: true, summary: `${tests.length} test(s) protect ${graph.nodes[id].name}.`, node: publicNode(graph.nodes[id]), tests };
  }
};

export const dbtFailedTests = {
  name: 'dbt_failed_tests', description: 'Return failed/error dbt tests from manifest plus run_results.json, optionally scoped to one node.',
  parameters: { type: 'object', properties: { ...projectProperties, node: { type: 'string' } } },
  async execute(args, { cwd }) {
    const graph = loadFromTool(args, cwd); let allowed = null;
    if (args.node) { const id = resolveDbtNode(graph, args.node); allowed = new Set(graph.testsByNode[id] || []); }
    const failed = Object.values(graph.nodes).filter(node => node.resourceType === 'test' && (!allowed || allowed.has(node.uniqueId)) && ['fail', 'failed', 'error'].includes(String(node.status?.status || '').toLowerCase())).map(publicNode);
    return { ok: true, summary: `${failed.length} failed/error dbt test(s) found.`, failedTests: failed };
  }
};

export const dbtModifiedImpact = {
  name: 'dbt_modified_impact', description: 'Compare current and baseline manifests and calculate downstream impact of changed/new nodes.',
  parameters: { type: 'object', required: ['baselineManifestPath'], properties: { ...projectProperties, baselineManifestPath: { type: 'string' }, depth: { type: 'integer', minimum: 1, maximum: 100 } } },
  async execute(args, { cwd }) {
    const graph = loadFromTool(args, cwd);
    const baseline = loadDbtGraph({ cwd, projectPath: args.projectPath || '.', manifestPath: args.baselineManifestPath });
    const modified = Object.values(graph.nodes).filter(node => {
      const old = baseline.nodes[node.uniqueId];
      return !old || (node.checksum || JSON.stringify(node.dependsOn)) !== (old.checksum || JSON.stringify(old.dependsOn));
    });
    const impacted = new Set();
    for (const node of modified) for (const id of descendants(graph, node.uniqueId, 'downstream', Number(args.depth) || 100).ids) impacted.add(id);
    return { ok: true, summary: `${modified.length} modified/new node(s), ${impacted.size} downstream impacted node(s).`, modified: modified.map(publicNode), impacted: [...impacted].map(id => publicNode(graph.nodes[id])) };
  }
};

export const dbtManifestTools = [dbtManifestSummary, dbtNode, dbtUpstream, dbtDownstream, dbtLineage, dbtImpact, dbtTestsForNode, dbtFailedTests, dbtModifiedImpact];
