import fs from 'node:fs';
import path from 'node:path';
function walk(dir, name, depth=4) {
  if (depth < 0 || !fs.existsSync(dir)) return null;
  for (const e of fs.readdirSync(dir,{withFileTypes:true})) {
    const p=path.join(dir,e.name); if (e.isFile() && e.name===name) return p;
    if (e.isDirectory() && !['node_modules','.git','target'].includes(e.name)) { const x=walk(p,name,depth-1); if(x) return x; }
  }
  return null;
}
export const dbtInspect = {
  name: 'dbt_inspect', description: 'Discover a dbt project and inspect dbt_project.yml/manifest.json metadata.',
  parameters: { type:'object', properties:{} },
  async execute(_, { cwd }) {
    const project = walk(cwd,'dbt_project.yml');
    const manifest = walk(cwd,'manifest.json');
    let manifestInfo = null;
    if (manifest) {
      try { const m=JSON.parse(fs.readFileSync(manifest,'utf8')); manifestInfo={ nodes:Object.keys(m.nodes||{}).length, sources:Object.keys(m.sources||{}).length, metadata:m.metadata||{} }; } catch {}
    }
    return { summary: project ? `dbt project found${manifest ? ' with manifest' : ''}.` : 'No dbt project found.', project: project && path.relative(cwd,project), manifest: manifest && path.relative(cwd,manifest), manifestInfo };
  }
};
