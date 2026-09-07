import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const defaults = {
  provider: 'mock',
  model: 'qwen3:8b',
  ollamaUrl: 'http://127.0.0.1:11434',
  mode: 'analyst',
  maxTurns: 6,
  trace: true,
  dbPath: '.ldh/sessions.db'
};

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return {}; }
}

export function loadConfig(cwd = process.cwd(), overrides = {}) {
  const globalConfig = readJson(path.join(os.homedir(), '.local-data-harness', 'config.json'));
  const projectConfig = readJson(path.join(cwd, '.ldh', 'config.json'));
  const env = {
    provider: process.env.LDH_PROVIDER,
    model: process.env.LDH_MODEL,
    ollamaUrl: process.env.LDH_OLLAMA_URL,
    mode: process.env.LDH_MODE,
    maxTurns: process.env.LDH_MAX_TURNS ? Number(process.env.LDH_MAX_TURNS) : undefined
  };
  const compact = (obj) => Object.fromEntries(Object.entries(obj).filter(([, value]) => value !== undefined));
  return { ...defaults, ...compact(globalConfig), ...compact(projectConfig), ...compact(env), ...compact(overrides) };
}
