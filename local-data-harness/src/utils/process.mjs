import { spawnSync } from 'node:child_process';
import path from 'node:path';

export function resolveCommand(command, cwd = process.cwd()) {
  if (!command) return command;
  if (command.includes('/') && !path.isAbsolute(command)) return path.resolve(cwd, command);
  return command;
}

export function runCommand(command, args = [], { cwd = process.cwd(), env = {}, timeout = 120000, maxOutput = 24000 } = {}) {
  const resolved = resolveCommand(command, cwd);
  const result = spawnSync(resolved, args, {
    cwd,
    env: { ...process.env, ...env },
    encoding: 'utf8',
    timeout,
    maxBuffer: Math.max(maxOutput * 4, 1024 * 1024)
  });
  if (result.error?.code === 'ENOENT') {
    return { available: false, ok: false, code: null, stdout: '', stderr: '', error: `Command not found: ${resolved}` };
  }
  const stdout = (result.stdout || '').slice(-maxOutput);
  const stderr = (result.stderr || '').slice(-maxOutput);
  return {
    available: true,
    ok: result.status === 0,
    code: result.status,
    signal: result.signal || null,
    stdout,
    stderr,
    error: result.error ? result.error.message : null
  };
}

export function probeCommand(command, args = ['--version'], options = {}) {
  return runCommand(command, args, { ...options, timeout: options.timeout || 15000, maxOutput: 4000 });
}
