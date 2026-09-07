import test from 'node:test';
import assert from 'node:assert/strict';
import { snowflakeQuery } from '../src/tools/snowflake.mjs';

test('blocks Snowflake writes before invoking connector', async () => {
  await assert.rejects(() => snowflakeQuery.execute({ sql: 'drop table important' }, { cwd: process.cwd() }), /read-only/i);
});
