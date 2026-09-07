import fs from 'node:fs';
import path from 'node:path';
import { airflowAudit, airflowStatus } from './airflow.mjs';
import { dbtQualityAudit, dbtParse, dbtTest } from './dbt-quality.mjs';
import { snowflakeConfigAudit, snowflakePing } from './snowflake.mjs';
import { sqlAnalyze } from './sql.mjs';

function walkSql(dir, out = [], depth = 6) {
  if (depth < 0 || !fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (['target', 'node_modules', '.git'].includes(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walkSql(p, out, depth - 1);
    else if (e.isFile() && e.name.endsWith('.sql')) out.push(p);
  }
  return out;
}

function readPolicy(cwd) {
  const file = path.join(cwd, '.ldh', 'quality.json');
  try { return { file, value: JSON.parse(fs.readFileSync(file, 'utf8')) }; }
  catch { return { file, value: { require: { airflow: false, dbt: false, snowflake: false }, maxSqlIssues: 20 } }; }
}

function checkResult(name, result, required) {
  const skipped = result?.available === false || /not .*found|not installed|not.*configured/i.test(result?.summary || '');
  if (skipped && !required) return { name, status: 'SKIP', required, summary: result?.summary || 'Skipped', result };
  return { name, status: result?.ok ? 'PASS' : 'FAIL', required, summary: result?.summary || '', result };
}

export const qualityPipeline = {
  name: 'quality_pipeline',
  description: 'Run the unified Airflow + dbt + Snowflake + SQL data-quality gate. level=static requires no cloud credentials; level=integration adds read-only live checks and dbt test.',
  parameters: { type: 'object', properties: { level: { type: 'string', enum: ['static', 'integration'] } } },
  async execute({ level = 'static' } = {}, { cwd }) {
    const policy = readPolicy(cwd);
    const airflow = await airflowAudit.execute({}, { cwd });
    const dbt = await dbtQualityAudit.execute({}, { cwd });
    const snowflake = await snowflakeConfigAudit.execute({}, { cwd });
    const sqlFiles = walkSql(path.join(cwd, 'models'));
    let sqlIssueCount = 0;
    const sql = [];
    for (const file of sqlFiles) {
      const analyzed = await sqlAnalyze.execute({ sql: fs.readFileSync(file, 'utf8') }, { cwd });
      sqlIssueCount += analyzed.issues?.length || 0;
      sql.push({ file: path.relative(cwd, file), ...analyzed });
    }
    const sqlResult = { ok: sqlIssueCount <= (policy.value.maxSqlIssues ?? 20), summary: `${sqlFiles.length} SQL model(s), ${sqlIssueCount} issue(s); threshold=${policy.value.maxSqlIssues ?? 20}.`, files: sql };

    const checks = [
      checkResult('airflow_static', airflow, Boolean(policy.value.require?.airflow)),
      checkResult('dbt_static', dbt, Boolean(policy.value.require?.dbt)),
      checkResult('snowflake_config', snowflake, Boolean(policy.value.require?.snowflake)),
      checkResult('sql_quality', sqlResult, true)
    ];

    if (level === 'integration') {
      const [airflowLive, dbtParseResult, dbtTestResult, snowflakeLive] = await Promise.all([
        airflowStatus.execute({}, { cwd }),
        dbtParse.execute({}, { cwd }),
        dbtTest.execute({}, { cwd }),
        snowflakePing.execute({}, { cwd })
      ]);
      checks.push(checkResult('airflow_live', airflowLive, Boolean(policy.value.requireLive?.airflow)));
      checks.push(checkResult('dbt_parse', dbtParseResult, Boolean(policy.value.requireLive?.dbt)));
      checks.push(checkResult('dbt_test', dbtTestResult, Boolean(policy.value.requireLive?.dbt)));
      checks.push(checkResult('snowflake_live', snowflakeLive, Boolean(policy.value.requireLive?.snowflake)));
    }

    const requiredFailures = checks.filter(c => c.status === 'FAIL' && c.required);
    const failures = checks.filter(c => c.status === 'FAIL');
    const passed = checks.filter(c => c.status === 'PASS').length;
    const evaluated = checks.filter(c => c.status !== 'SKIP').length;
    const score = evaluated ? Math.round((passed / evaluated) * 100) : 0;
    return {
      ok: requiredFailures.length === 0,
      summary: `Quality gate ${requiredFailures.length ? 'FAILED' : 'PASSED'}: ${passed}/${checks.length} checks passed, ${failures.length} failed, score=${score}.`,
      level,
      policy: { file: path.relative(cwd, policy.file), ...policy.value },
      score,
      checks
    };
  }
};
