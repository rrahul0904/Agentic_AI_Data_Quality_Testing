import path from 'node:path';
import fs from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

export const sqlAnalyze = {
  name: 'sql_analyze', description: 'Deterministically review SQL for common anti-patterns and unsafe statements.',
  parameters: { type: 'object', properties: { sql: { type: 'string' } }, required: ['sql'] },
  async execute({ sql }) {
    const s = String(sql || '');
    const issues = [];
    const add = (rule, severity, message) => issues.push({ rule, severity, message });
    if (/select\s+\*/i.test(s)) add('select-star', 'warning', 'SELECT * couples consumers to schema changes.');
    if (/\bcross\s+join\b/i.test(s)) add('cross-join', 'warning', 'CROSS JOIN can multiply row counts dramatically.');
    if (/\b(delete|update)\b/i.test(s) && !/\bwhere\b/i.test(s)) add('write-without-where', 'critical', 'UPDATE/DELETE without WHERE may affect every row.');
    if (/\b(drop\s+(database|schema)|truncate\b)/i.test(s)) add('destructive-ddl', 'critical', 'Destructive DDL is blocked by policy.');
    if (/\bnot\s+in\s*\(/i.test(s)) add('not-in-null', 'warning', 'NOT IN can behave unexpectedly when NULL appears in the subquery.');
    if (/\bwhere\b[^;]*(lower|upper|date|cast)\s*\([^)]*\)\s*(=|>|<|like)/i.test(s)) add('non-sargable', 'info', 'Function-wrapped predicate may prevent index pruning.');
    const statement = (s.match(/^\s*(\w+)/)?.[1] || '').toUpperCase();
    const safeRead = ['SELECT', 'WITH', 'EXPLAIN', 'PRAGMA'].includes(statement);
    return { summary: `${issues.length} SQL issue(s) found; statement=${statement || 'UNKNOWN'}; readOnly=${safeRead}.`, statement, readOnly: safeRead, issues };
  }
};

export const sqlExecute = {
  name: 'sql_execute', description: 'Execute SQL against the project-local SQLite database; read-only in analyst/plan, writes allowed in builder.',
  parameters: { type: 'object', properties: { sql: { type: 'string' }, db: { type: 'string' } }, required: ['sql'] },
  async execute({ sql, db = '.ldh/demo.db' }, { cwd, mode }) {
    const analysis = await sqlAnalyze.execute({ sql });
    if (analysis.issues.some(i => i.rule === 'destructive-ddl')) throw new Error('Destructive SQL is hard-blocked.');
    if (mode !== 'builder' && !analysis.readOnly) throw new Error('Only read-only SQL is allowed outside builder mode.');
    const full = path.resolve(cwd, db); fs.mkdirSync(path.dirname(full), { recursive: true });
    const database = new DatabaseSync(full);
    if (analysis.readOnly) return { rows: database.prepare(sql).all(), rowCount: database.prepare(sql).all().length };
    const result = database.prepare(sql).run(); return { changes: result.changes, lastInsertRowid: String(result.lastInsertRowid ?? '') };
  }
};

export const sqlLineage = {
  name: 'sql_lineage', description: 'Extract draft table/column lineage from SQL without an LLM.',
  parameters: { type: 'object', properties: { sql: { type: 'string' } }, required: ['sql'] },
  async execute({ sql }) {
    const text = String(sql);
    const ctes = new Set([...text.matchAll(/(?:\bwith\b|,)\s*([A-Za-z_]\w*)\s+as\s*\(/gi)].map(m => m[1]));
    const tables = [...text.matchAll(/\b(?:from|join)\s+([\w."`-]+)/gi)].map(m => m[1].replace(/["`]/g, '')).filter(t => !ctes.has(t));
    const selects = [...text.matchAll(/\bselect\b([\s\S]*?)\bfrom\b/gi)];
    const select = selects.at(-1)?.[1] || '';
    const columns = select.split(',').map(x => x.trim()).filter(Boolean).map(expr => {
      const alias = expr.match(/\bas\s+([\w"]+)\s*$/i)?.[1]?.replace(/"/g, '') || expr.split('.').at(-1)?.replace(/\W+/g, '_');
      const refs = [...expr.matchAll(/\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b/g)].map(m => `${m[1]}.${m[2]}`);
      return { output: alias, sources: refs, expression: expr };
    });
    return { summary: `${tables.length} source table(s), ${columns.length} projected expression(s).`, tables: [...new Set(tables)], columns };
  }
};
