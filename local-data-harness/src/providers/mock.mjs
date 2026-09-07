import fs from 'node:fs';
import path from 'node:path';

export class MockProvider {
  async chat({ messages, cwd }) {
    const last = messages.at(-1);
    if (last?.role === 'tool') {
      const result = JSON.parse(last.content);
      return { content: summarize(result), toolCalls: [] };
    }
    const prompt = messages.filter(m => m.role === 'user').at(-1)?.content || '';
    const lower = prompt.toLowerCase();
    const sqlFile = findSqlFile(prompt, cwd);
    if (lower.includes('discover')) return call('stack_discover', {});
    if (lower.includes('pii')) return sqlFile ? call('pii_scan', { text: fs.readFileSync(sqlFile, 'utf8') }) : call('pii_scan', { text: prompt });
    if (lower.startsWith('run ') || lower.startsWith('query ')) return call('sql_execute', { sql: extractSql(prompt) });
    if (lower.includes('lineage')) return sqlFile ? call('sql_lineage', { sql: fs.readFileSync(sqlFile, 'utf8') }) : call('sql_lineage', { sql: extractSql(prompt) });
    if (lower.includes('analy') || lower.includes('review') || lower.includes('sql')) {
      if (sqlFile) return call('sql_analyze', { sql: fs.readFileSync(sqlFile, 'utf8') });
      return call('sql_analyze', { sql: extractSql(prompt) });
    }
    if (lower.includes('dbt')) return call('dbt_inspect', {});
    return { content: 'Local Data Harness is running. Try: discover, analyze models/orders.sql, lineage models/orders.sql, pii <text>, or dbt inspect.', toolCalls: [] };
  }
}
function call(name, args) { return { content: '', rawToolCalls: [{ function: { name, arguments: args } }], toolCalls: [{ name, arguments: args }] }; }
function findSqlFile(prompt, cwd) {
  const matches = prompt.match(/[\w./-]+\.sql\b/gi) || [];
  for (const item of matches) { const p = path.resolve(cwd, item); if (fs.existsSync(p)) return p; }
}
function extractSql(prompt) { const idx = prompt.search(/\b(select|with|insert|update|delete|create)\b/i); return idx >= 0 ? prompt.slice(idx) : prompt; }
function summarize(r) {
  if (r.error) return `Tool error: ${r.error}`;
  if (r.summary) return r.summary + (r.issues?.length ? `\nIssues: ${r.issues.map(x => x.message).join('; ')}` : '');
  return JSON.stringify(r, null, 2);
}
