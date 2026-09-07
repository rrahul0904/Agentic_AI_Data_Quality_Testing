import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { probeCommand } from '../utils/process.mjs';

function probe(name, command, args = ['--version'], cwd) {
  const result = probeCommand(command, args, { cwd });
  return { name, configured: command, available: result.available && result.ok, version: result.available ? (result.stdout || result.stderr).trim().split('\n')[0] : null };
}

export const stackDiscover = {
  name: 'stack_discover',
  description: 'Discover local data-engineering tools, dbt/Snowflake profiles, and project markers without changing anything.',
  parameters: { type: 'object', properties: {} },
  async execute(_, { cwd }) {
    const candidates = [
      ['dbt', process.env.LDH_DBT_BIN || 'dbt', ['--version']],
      ['airflow', process.env.LDH_AIRFLOW_BIN || 'airflow', ['version']],
      ['python', process.env.LDH_PYTHON_BIN || 'python3', ['--version']],
      ['snow', 'snow', ['--version']],
      ['sqlfluff', 'sqlfluff', ['--version']],
      ['duckdb', 'duckdb', ['--version']],
      ['psql', 'psql', ['--version']],
      ['docker', 'docker', ['--version']],
      ['ollama', 'ollama', ['--version']],
      ['dagster', 'dagster', ['--version']]
    ];
    const tools = Object.fromEntries(candidates.map(([name, cmd, args]) => [name, probe(name, cmd, args, cwd)]));
    const profileCandidates = [
      process.env.DBT_PROFILES_DIR && path.join(process.env.DBT_PROFILES_DIR, 'profiles.yml'),
      path.join(cwd, 'profiles.yml'),
      path.join(os.homedir(), '.dbt', 'profiles.yml')
    ].filter(Boolean);
    const snowflakeCandidates = [
      path.join(os.homedir(), '.snowflake', 'connections.toml'),
      path.join(os.homedir(), '.config', 'snowflake', 'connections.toml'),
      path.join(os.homedir(), 'Library', 'Application Support', 'snowflake', 'connections.toml')
    ];
    const markers = ['dbt_project.yml', 'package.json', 'pyproject.toml', 'requirements.txt'].filter(x => fs.existsSync(path.join(cwd, x)));
    const found = Object.values(tools).filter(t => t.available).length;
    return {
      summary: `Found ${found} known tool(s); ${markers.length} project marker(s).`,
      tools,
      dbtProfiles: profileCandidates.find(fs.existsSync) || null,
      snowflakeConnections: snowflakeCandidates.find(fs.existsSync) || null,
      markers
    };
  }
};
