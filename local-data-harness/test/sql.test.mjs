import test from 'node:test'; import assert from 'node:assert/strict'; import { sqlAnalyze, sqlLineage } from '../src/tools/sql.mjs';
test('detects SELECT star', async()=>{const r=await sqlAnalyze.execute({sql:'select * from orders'});assert.equal(r.issues[0].rule,'select-star');});
test('blocks destructive ddl marker', async()=>{const r=await sqlAnalyze.execute({sql:'TRUNCATE TABLE orders'});assert.ok(r.issues.some(x=>x.rule==='destructive-ddl'));});
test('extracts tables', async()=>{const r=await sqlLineage.execute({sql:'select o.id from orders o join customers c on o.customer_id=c.id'});assert.deepEqual(r.tables,['orders','customers']);});
