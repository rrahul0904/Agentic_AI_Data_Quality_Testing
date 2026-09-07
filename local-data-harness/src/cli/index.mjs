#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { createApp } from '../core/app.mjs';
import { repl } from './repl.mjs';
import { serve } from './server.mjs';

const argv = process.argv.slice(2);
const command = argv[0] && !argv[0].startsWith('-') ? argv.shift() : 'repl';
function value(flag, fallback) { const i = argv.indexOf(flag); return i >= 0 ? argv[i + 1] : fallback; }
const cwd = path.resolve(value('--cwd', process.cwd()));
const mode = value('--mode', undefined);
const provider = value('--provider', undefined);
const model = value('--model', undefined);
const app = createApp({ cwd, overrides: { mode, provider, model } });

function printJson(value) { console.log(JSON.stringify(value, null, 2)); }
function promptArgs() {
  const flagsWithValues = new Set(['--cwd', '--mode', '--provider', '--model', '--level']);
  const skip = new Set();
  argv.forEach((v, i) => { if (flagsWithValues.has(v)) { skip.add(i); skip.add(i + 1); } });
  return argv.filter((_, i) => !skip.has(i)).join(' ');
}

if (command === 'repl') await repl(app);
else if (command === 'ask') {
  const prompt = promptArgs();
  if (!prompt) { console.error('Usage: ldh ask "question"'); process.exit(2); }
  const r = await app.agent.run(prompt);
  console.log(r.answer);
}
else if (command === 'discover') printJson(await app.registry.execute('stack_discover', {}, { cwd }));
else if (command === 'quality') {
  const level = value('--level', 'static');
  const r = await app.registry.execute('quality_pipeline', { level }, { cwd });
  printJson(r);
  if (!r.ok) process.exitCode = 1;
}
else if (command === 'airflow') printJson(await app.registry.execute('airflow_audit', {}, { cwd }));
else if (command === 'airflow-status') printJson(await app.registry.execute('airflow_status', {}, { cwd }));
else if (command === 'dbt-audit') printJson(await app.registry.execute('dbt_quality_audit', {}, { cwd }));
else if (command === 'dbt-test') printJson(await app.registry.execute('dbt_test', {}, { cwd }));
else if (command === 'snowflake') printJson(await app.registry.execute('snowflake_config_audit', {}, { cwd }));
else if (command === 'snowflake-ping') printJson(await app.registry.execute('snowflake_ping', {}, { cwd }));
else if (command === 'tools') console.table(app.registry.list().map(x => ({ name: x.name, description: x.description })));
else if (command === 'sessions') console.table(app.store.recent(25));
else if (command === 'serve') serve(app, Number(value('--port', '4096')));
else if (command === 'init') {
  const d = path.join(cwd, '.ldh'); fs.mkdirSync(d, { recursive: true });
  const f = path.join(d, 'config.json');
  if (!fs.existsSync(f)) fs.writeFileSync(f, JSON.stringify({ provider: 'mock', model: 'qwen3:8b', mode: 'analyst' }, null, 2));
  const q = path.join(d, 'quality.json');
  if (!fs.existsSync(q)) fs.writeFileSync(q, JSON.stringify({ require: { airflow: false, dbt: false, snowflake: false }, requireLive: { airflow: false, dbt: false, snowflake: false }, maxSqlIssues: 20 }, null, 2));
  console.log(`Created ${f}\nCreated ${q}`);
}
else { console.error(`Unknown command: ${command}`); process.exit(2); }
