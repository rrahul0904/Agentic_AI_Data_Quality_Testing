import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { qualityPipeline } from '../src/tools/quality.mjs';

test('static quality pipeline passes demo', async () => {
  const cwd = path.resolve('examples/demo');
  const result = await qualityPipeline.execute({ level: 'static' }, { cwd });
  assert.equal(result.ok, true);
  assert.ok(result.checks.some(c => c.name === 'airflow_static' && c.status === 'PASS'));
  assert.ok(result.checks.some(c => c.name === 'dbt_static' && c.status === 'PASS'));
});
