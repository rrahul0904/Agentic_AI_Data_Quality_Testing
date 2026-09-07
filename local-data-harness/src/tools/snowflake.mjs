import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runCommand } from '../utils/process.mjs';

const READ_ONLY = /^\s*(select|with|show|describe|desc|explain)\b/i;
const BLOCKED = /\b(insert|update|delete|merge|create|alter|drop|truncate|copy|put|remove|grant|revoke|call)\b/i;

function connectionTomlCandidates() {
  return [
    path.join(os.homedir(), '.snowflake', 'connections.toml'),
    path.join(os.homedir(), '.config', 'snowflake', 'connections.toml'),
    path.join(os.homedir(), 'Library', 'Application Support', 'snowflake', 'connections.toml')
  ];
}

function envPresence() {
  const names = ['SNOWFLAKE_ACCOUNT', 'SNOWFLAKE_USER', 'SNOWFLAKE_PASSWORD', 'SNOWFLAKE_WAREHOUSE', 'SNOWFLAKE_DATABASE', 'SNOWFLAKE_SCHEMA', 'SNOWFLAKE_ROLE', 'SNOWFLAKE_CONNECTION_NAME'];
  return Object.fromEntries(names.map(name => [name, Boolean(process.env[name])]));
}

function invokeBridge(operation, payload, cwd) {
  const pythonBin = process.env.LDH_PYTHON_BIN || 'python3';
  const bridge = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../scripts/snowflake_bridge.py');
  const result = runCommand(pythonBin, [bridge, operation, JSON.stringify(payload || {})], { cwd, timeout: 120000, maxOutput: 32000 });
  if (!result.available) return { available: false, ok: false, summary: `Python is not available: ${result.error}` };
  const text = (result.stdout || '').trim();
  if (text) {
    try { return JSON.parse(text); } catch {}
  }
  return { available: true, ok: false, summary: 'Snowflake bridge failed.', stderr: result.stderr, code: result.code };
}

export const snowflakeConfigAudit = {
  name: 'snowflake_config_audit',
  description: 'Audit Snowflake connection configuration without exposing secrets.',
  parameters: { type: 'object', properties: {} },
  async execute(_, { cwd }) {
    const env = envPresence();
    const toml = connectionTomlCandidates().filter(fs.existsSync);
    const hasNamedConnection = env.SNOWFLAKE_CONNECTION_NAME;
    const requiredEnv = ['SNOWFLAKE_ACCOUNT', 'SNOWFLAKE_USER'];
    const missing = hasNamedConnection ? [] : requiredEnv.filter(k => !env[k]);
    return {
      ok: hasNamedConnection || missing.length === 0 || toml.length > 0,
      summary: hasNamedConnection ? 'Snowflake named connection configured.' : toml.length ? 'Snowflake connections.toml detected.' : missing.length ? `Snowflake live credentials not fully configured (${missing.join(', ')} missing).` : 'Snowflake environment configuration detected.',
      env,
      connectionFiles: toml,
      cwd,
      note: 'Secret values are never returned.'
    };
  }
};

export const snowflakePing = {
  name: 'snowflake_ping',
  description: 'Open a Snowflake connection and run a read-only health query.',
  parameters: { type: 'object', properties: {} },
  async execute(_, { cwd }) { return invokeBridge('ping', {}, cwd); }
};

export const snowflakeQuery = {
  name: 'snowflake_query',
  description: 'Execute a bounded read-only Snowflake query (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN only).',
  parameters: { type: 'object', required: ['sql'], properties: { sql: { type: 'string' }, maxRows: { type: 'integer', minimum: 1, maximum: 500 } } },
  async execute({ sql, maxRows = 100 }, { cwd }) {
    if (!READ_ONLY.test(sql || '') || BLOCKED.test(sql || '')) throw new Error('Only read-only Snowflake statements are allowed.');
    return invokeBridge('query', { sql, maxRows: Math.max(1, Math.min(500, Number(maxRows) || 100)) }, cwd);
  }
};
