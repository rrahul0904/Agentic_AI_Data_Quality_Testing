import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { airflowAudit } from '../src/tools/airflow.mjs';

test('audits example airflow DAG', async () => {
  const cwd = path.resolve('examples/demo');
  const result = await airflowAudit.execute({}, { cwd });
  assert.equal(result.ok, true);
  assert.equal(result.integration.dbt, true);
  assert.equal(result.integration.snowflake, true);
  assert.ok(result.files.some(f => f.dagIds.includes('ldh_data_quality_pipeline')));
});
