import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';

export class SessionStore {
  constructor(cwd, dbPath = '.ldh/sessions.db') {
    const full = path.resolve(cwd, dbPath);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    this.db = new DatabaseSync(full);
    this.db.exec(`
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, finished_at TEXT,
        prompt TEXT NOT NULL, answer TEXT, mode TEXT, provider TEXT, status TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, created_at TEXT NOT NULL,
        type TEXT NOT NULL, payload TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS tool_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, created_at TEXT NOT NULL,
        tool TEXT NOT NULL, args TEXT, result TEXT, duration_ms INTEGER
      );
    `);
  }
  createSession({ prompt, mode, provider }) {
    const id = crypto.randomUUID();
    this.db.prepare('INSERT INTO sessions(id,created_at,prompt,mode,provider,status) VALUES(?,?,?,?,?,?)')
      .run(id, new Date().toISOString(), prompt, mode, provider, 'running');
    return id;
  }
  logEvent(id, type, payload) {
    this.db.prepare('INSERT INTO events(session_id,created_at,type,payload) VALUES(?,?,?,?)')
      .run(id, new Date().toISOString(), type, JSON.stringify(payload));
  }
  logTool(id, tool, args, result, durationMs) {
    this.db.prepare('INSERT INTO tool_calls(session_id,created_at,tool,args,result,duration_ms) VALUES(?,?,?,?,?,?)')
      .run(id, new Date().toISOString(), tool, JSON.stringify(args), JSON.stringify(result), durationMs);
  }
  finishSession(id, answer) {
    this.db.prepare('UPDATE sessions SET finished_at=?, answer=?, status=? WHERE id=?')
      .run(new Date().toISOString(), answer, 'done', id);
  }
  failSession(id, error) {
    this.db.prepare('UPDATE sessions SET finished_at=?, answer=?, status=? WHERE id=?')
      .run(new Date().toISOString(), error, 'failed', id);
  }
  recent(limit = 10) { return this.db.prepare('SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?').all(limit); }
}
