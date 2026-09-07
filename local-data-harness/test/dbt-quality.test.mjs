import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { dbtQualityAudit } from '../src/tools/dbt-quality.mjs';

test('detects dbt quality tests', async () => {
  const cwd = path.resolve('examples/demo');
  const result = await dbtQualityAudit.execute({}, { cwd });
  assert.equal(result.ok, true);
  assert.equal(result.coverage.modelCount, 1);
  assert.ok(result.coverage.totalTests >= 4);
});
