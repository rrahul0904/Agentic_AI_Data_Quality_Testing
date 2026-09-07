import fs from 'node:fs';
import path from 'node:path';
import { probeCommand, runCommand } from '../utils/process.mjs';

function walkPython(dir, out = [], depth = 6) {
  if (depth < 0 || !fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || entry.name === '__pycache__' || entry.name === 'node_modules') continue;
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walkPython(file, out, depth - 1);
    else if (entry.isFile() && entry.name.endsWith('.py')) out.push(file);
  }
  return out;
}

function findDagRoots(cwd) {
  const candidates = [
    path.join(cwd, 'airflow', 'dags'),
    path.join(cwd, 'dags'),
    path.join(cwd, 'src', 'dags')
  ];
  return candidates.filter(fs.existsSync);
}

function extractDagInfo(source, file, cwd) {
  const ids = new Set();
  for (const re of [/dag_id\s*=\s*["']([^"']+)["']/g, /DAG\(\s*["']([^"']+)["']/g, /@dag\([\s\S]{0,500}?dag_id\s*=\s*["']([^"']+)["']/g]) {
    for (const match of source.matchAll(re)) ids.add(match[1]);
  }
  return {
    file: path.relative(cwd, file),
    dagIds: [...ids],
    hasSchedule: /schedule\s*=|schedule_interval\s*=/.test(source),
    catchupDisabled: /catchup\s*=\s*False/.test(source),
    hasRetries: /[\"']?retries[\"']?\s*[:=]/.test(source),
    usesDbt: /\bdbt\s+(build|test|run|seed|snapshot)\b|dbt[_-]/i.test(source),
    usesSnowflake: /Snowflake(Hook|Operator|SqlApi)|snowflake_default|snowflake\.connector/i.test(source)
  };
}

export const airflowAudit = {
  name: 'airflow_audit',
  description: 'Statically inspect Airflow DAG files, compile Python syntax, and report orchestration/data-quality coverage.',
  parameters: { type: 'object', properties: {} },
  async execute(_, { cwd }) {
    const roots = findDagRoots(cwd);
    const files = roots.flatMap(root => walkPython(root));
    const pythonBin = process.env.LDH_PYTHON_BIN || 'python3';
    const details = [];
    const duplicateIds = new Map();
    for (const file of files) {
      const source = fs.readFileSync(file, 'utf8');
      const info = extractDagInfo(source, file, cwd);
      const compile = runCommand(pythonBin, ['-c', 'import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_text(), sys.argv[1], \"exec\")', file], { cwd, timeout: 20000, maxOutput: 4000 });
      info.syntaxOk = compile.ok;
      info.syntaxError = compile.ok ? null : (compile.stderr || compile.error || 'Python compile failed').trim();
      for (const id of info.dagIds) duplicateIds.set(id, [...(duplicateIds.get(id) || []), info.file]);
      details.push(info);
    }
    const duplicates = [...duplicateIds.entries()].filter(([, locations]) => locations.length > 1).map(([dagId, locations]) => ({ dagId, locations }));
    const issues = [];
    for (const d of details) {
      if (!d.syntaxOk) issues.push(`${d.file}: Python syntax error`);
      if (!d.dagIds.length) issues.push(`${d.file}: no DAG id detected`);
      if (!d.hasSchedule) issues.push(`${d.file}: no schedule detected`);
      if (!d.catchupDisabled) issues.push(`${d.file}: catchup=False not detected`);
    }
    for (const d of duplicates) issues.push(`duplicate dag_id ${d.dagId}: ${d.locations.join(', ')}`);
    return {
      summary: files.length ? `${files.length} Airflow DAG file(s) inspected; ${issues.length} issue(s).` : 'No Airflow DAG files found.',
      roots: roots.map(r => path.relative(cwd, r)),
      files: details,
      duplicates,
      integration: { dbt: details.some(d => d.usesDbt), snowflake: details.some(d => d.usesSnowflake) },
      issues,
      ok: files.length > 0 && issues.length === 0
    };
  }
};

export const airflowStatus = {
  name: 'airflow_status',
  description: 'Check whether an Airflow CLI is installed and, when available, list parsed DAGs.',
  parameters: { type: 'object', properties: {} },
  async execute(_, { cwd }) {
    const airflowBin = process.env.LDH_AIRFLOW_BIN || 'airflow';
    const version = probeCommand(airflowBin, ['version'], { cwd });
    if (!version.available) return { available: false, ok: false, summary: 'Airflow CLI is not installed/configured.', installHint: 'Run scripts/bootstrap-data-stack.sh or set LDH_AIRFLOW_BIN.' };
    const dags = runCommand(airflowBin, ['dags', 'list'], { cwd, timeout: 60000 });
    return { available: true, ok: version.ok && dags.ok, version: (version.stdout || version.stderr).trim(), dags: dags.stdout, stderr: dags.stderr };
  }
};

export const airflowDagTest = {
  name: 'airflow_dag_test',
  description: 'Execute Airflow dags test for one DAG. This can run task code and external integrations, so it is builder-only.',
  capability: 'externalWrite',
  parameters: {
    type: 'object',
    required: ['dagId'],
    properties: {
      dagId: { type: 'string' },
      logicalDate: { type: 'string' },
      dagFile: { type: 'string' }
    }
  },
  async execute({ dagId, logicalDate, dagFile }, { cwd }) {
    if (!/^[A-Za-z0-9_.-]+$/.test(dagId || '')) throw new Error('Invalid dagId');
    const airflowBin = process.env.LDH_AIRFLOW_BIN || 'airflow';
    const args = ['dags', 'test', dagId];
    if (logicalDate) args.push(logicalDate);
    if (dagFile) args.push('--dagfile-path', path.resolve(cwd, dagFile));
    const result = runCommand(airflowBin, args, { cwd, timeout: 15 * 60 * 1000 });
    return { ...result, summary: result.ok ? `Airflow DAG ${dagId} test passed.` : `Airflow DAG ${dagId} test failed.` };
  }
};
