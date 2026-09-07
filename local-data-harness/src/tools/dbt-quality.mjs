import fs from 'node:fs';
import path from 'node:path';
import { probeCommand, runCommand } from '../utils/process.mjs';

function walk(dir, predicate, out = [], depth = 7) {
  if (depth < 0 || !fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (['node_modules', '.git', 'target', 'logs', '__pycache__'].includes(entry.name)) continue;
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file, predicate, out, depth - 1);
    else if (entry.isFile() && predicate(file)) out.push(file);
  }
  return out;
}

export function findDbtProject(cwd) {
  const matches = walk(cwd, file => path.basename(file) === 'dbt_project.yml');
  return matches[0] || null;
}

function parseRunResults(projectDir) {
  const file = path.join(projectDir, 'target', 'run_results.json');
  if (!fs.existsSync(file)) return null;
  try {
    const json = JSON.parse(fs.readFileSync(file, 'utf8'));
    const results = (json.results || []).map(r => ({ unique_id: r.unique_id, status: r.status, execution_time: r.execution_time, message: r.message || null }));
    const counts = results.reduce((acc, r) => { acc[r.status] = (acc[r.status] || 0) + 1; return acc; }, {});
    return { file, counts, results };
  } catch (error) { return { file, error: error.message }; }
}

function staticCoverage(projectDir) {
  const modelFiles = walk(path.join(projectDir, 'models'), file => file.endsWith('.sql'));
  const yamlFiles = walk(path.join(projectDir, 'models'), file => /\.ya?ml$/i.test(file));
  const yamlText = yamlFiles.map(f => fs.readFileSync(f, 'utf8')).join('\n');
  const genericTests = ['not_null', 'unique', 'relationships', 'accepted_values'].reduce((acc, name) => {
    acc[name] = (yamlText.match(new RegExp(`\\b${name}\\b`, 'g')) || []).length;
    return acc;
  }, {});
  const singularTests = walk(path.join(projectDir, 'tests'), file => file.endsWith('.sql')).length;
  const totalTests = Object.values(genericTests).reduce((a, b) => a + b, 0) + singularTests;
  const declaredModels = [...yamlText.matchAll(/^  -\s+name\s*:\s*([A-Za-z0-9_-]+)\s*$/gm)].map(m => m[1]);
  const modelNames = modelFiles.map(f => path.basename(f, '.sql'));
  const coveredModels = modelNames.filter(name => declaredModels.includes(name));
  return {
    models: modelFiles.map(f => path.relative(projectDir, f)),
    modelCount: modelFiles.length,
    schemaFiles: yamlFiles.map(f => path.relative(projectDir, f)),
    declaredModels,
    coveredModels,
    modelDocumentationCoverage: modelFiles.length ? coveredModels.length / modelFiles.length : 0,
    genericTests,
    singularTests,
    totalTests
  };
}

export const dbtQualityAudit = {
  name: 'dbt_quality_audit',
  description: 'Inspect dbt model/test coverage and parse the latest run_results.json without requiring dbt to be installed.',
  parameters: { type: 'object', properties: {} },
  async execute(_, { cwd }) {
    const projectFile = findDbtProject(cwd);
    if (!projectFile) return { ok: false, summary: 'No dbt_project.yml found.' };
    const projectDir = path.dirname(projectFile);
    const coverage = staticCoverage(projectDir);
    const runResults = parseRunResults(projectDir);
    const issues = [];
    if (!coverage.schemaFiles.length) issues.push('No dbt schema YAML files found.');
    if (!coverage.totalTests) issues.push('No dbt generic/data tests detected.');
    if (coverage.modelDocumentationCoverage < 1) issues.push(`Only ${coverage.coveredModels.length}/${coverage.modelCount} SQL models are declared in schema YAML.`);
    if (runResults?.counts?.fail || runResults?.counts?.error) issues.push('Latest dbt run_results.json contains failures/errors.');
    return {
      ok: issues.length === 0,
      summary: `${coverage.modelCount} dbt model(s), ${coverage.totalTests} static test reference(s), ${issues.length} issue(s).`,
      projectDir: path.relative(cwd, projectDir) || '.',
      coverage,
      runResults: runResults ? { ...runResults, file: path.relative(cwd, runResults.file) } : null,
      issues
    };
  }
};

function dbtRunTool({ name, command, description, capability }) {
  return {
    name,
    description,
    ...(capability ? { capability } : {}),
    parameters: {
      type: 'object',
      properties: {
        select: { type: 'string' },
        exclude: { type: 'string' },
        target: { type: 'string' },
        profilesDir: { type: 'string' }
      }
    },
    async execute(args, { cwd }) {
      const projectFile = findDbtProject(cwd);
      if (!projectFile) return { available: false, ok: false, summary: 'No dbt_project.yml found.' };
      const projectDir = path.dirname(projectFile);
      const dbtBin = process.env.LDH_DBT_BIN || 'dbt';
      const probe = probeCommand(dbtBin, ['--version'], { cwd: projectDir });
      if (!probe.available) return { available: false, ok: false, summary: 'dbt CLI is not installed/configured.', installHint: 'Run scripts/bootstrap-data-stack.sh or set LDH_DBT_BIN.' };
      const cliArgs = [command, '--project-dir', projectDir];
      if (args.select) cliArgs.push('--select', args.select);
      if (args.exclude) cliArgs.push('--exclude', args.exclude);
      if (args.target) cliArgs.push('--target', args.target);
      if (args.profilesDir) cliArgs.push('--profiles-dir', path.resolve(cwd, args.profilesDir));
      const result = runCommand(dbtBin, cliArgs, { cwd: projectDir, timeout: command === 'build' ? 30 * 60 * 1000 : 15 * 60 * 1000 });
      const runResults = parseRunResults(projectDir);
      return {
        ...result,
        version: (probe.stdout || probe.stderr).trim().split('\n')[0],
        command: [dbtBin, ...cliArgs].join(' '),
        runResults: runResults ? { ...runResults, file: path.relative(cwd, runResults.file) } : null,
        summary: result.ok ? `dbt ${command} passed.` : `dbt ${command} failed.`
      };
    }
  };
}

export const dbtParse = dbtRunTool({ name: 'dbt_parse', command: 'parse', description: 'Run dbt parse to validate project/Jinja configuration.' });
export const dbtTest = dbtRunTool({ name: 'dbt_test', command: 'test', description: 'Run dbt data/unit tests and parse run_results.json.' });
export const dbtBuild = dbtRunTool({ name: 'dbt_build', command: 'build', description: 'Run dbt build in DAG order; builder-only because models/seeds/snapshots can write to the warehouse.', capability: 'externalWrite' });
