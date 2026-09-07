import fs from 'node:fs';
import path from 'node:path';
function safe(cwd, input) {
  const root = path.resolve(cwd), full = path.resolve(root, input || '.');
  if (!full.startsWith(root + path.sep) && full !== root) throw new Error('Path escapes workspace.');
  return full;
}
export const fileList = {
  name: 'file_list', description: 'List files inside the current workspace.',
  parameters: { type: 'object', properties: { path: { type: 'string' } } },
  async execute({ path: p = '.' }, { cwd }) { return fs.readdirSync(safe(cwd,p), { withFileTypes: true }).map(x => ({ name:x.name, type:x.isDirectory()?'dir':'file' })); }
};
export const fileRead = {
  name: 'file_read', description: 'Read a UTF-8 text file inside the current workspace.',
  parameters: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] },
  async execute({ path: p }, { cwd }) { const content=fs.readFileSync(safe(cwd,p),'utf8'); return { path:p, content:content.slice(0,120000), truncated:content.length>120000 }; }
};
export const fileWrite = {
  name: 'file_write', description: 'Write a UTF-8 text file inside the workspace.', capability: 'fileWrite',
  parameters: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' } }, required: ['path','content'] },
  async execute({ path: p, content }, { cwd }) { const full=safe(cwd,p); fs.mkdirSync(path.dirname(full),{recursive:true}); fs.writeFileSync(full,content); return { path:p, bytes:Buffer.byteLength(content) }; }
};
