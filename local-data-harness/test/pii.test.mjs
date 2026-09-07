import test from 'node:test'; import assert from 'node:assert/strict'; import { piiScan } from '../src/tools/pii.mjs';
test('detects email and ssn', async()=>{const r=await piiScan.execute({text:'a@example.com 123-45-6789'});assert.equal(r.findings.length,2);});
