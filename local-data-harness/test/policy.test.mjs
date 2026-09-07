import test from 'node:test'; import assert from 'node:assert/strict'; import { createRegistry } from '../src/tools/index.mjs';
test('analyst blocks file writes', async()=>{const r=createRegistry('analyst');await assert.rejects(()=>r.execute('file_write',{path:'x',content:'y'},{cwd:process.cwd()}),/blocked/);});

test('analyst permits read-only local SQL but blocks writes', async()=>{const r=createRegistry('analyst');const cwd=process.cwd();const rows=await r.execute('sql_execute',{sql:'select 1 as ok',db:'.ldh/test-policy.db'},{cwd});assert.equal(rows.rows[0].ok,1);await assert.rejects(()=>r.execute('sql_execute',{sql:'create table x(id int)',db:'.ldh/test-policy.db'},{cwd}),/read-only/);});
