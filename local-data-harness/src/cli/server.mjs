import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const webIndex = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../web/index.html');
export function serve(app, port=4096) {
  const server=http.createServer(async (req,res)=>{
    try{
      if(req.url==='/' && req.method==='GET'){res.setHeader('content-type','text/html; charset=utf-8');res.end(fs.readFileSync(webIndex));return;}
      res.setHeader('content-type','application/json');
      if(req.url==='/health'){res.end(JSON.stringify({ok:true,provider:app.config.provider,mode:app.config.mode}));return;}
      if(req.url==='/api/tools'){res.end(JSON.stringify(app.registry.list()));return;}
      if(req.url==='/api/sessions'){res.end(JSON.stringify(app.store.recent(25)));return;}
      if(req.url==='/api/ask' && req.method==='POST'){
        let body=''; for await(const c of req) body+=c; const {prompt}=JSON.parse(body||'{}');
        if(!prompt) throw new Error('prompt is required'); const result=await app.agent.run(prompt); res.end(JSON.stringify(result)); return;
      }
      res.statusCode=404; res.end(JSON.stringify({error:'not found'}));
    }catch(e){res.statusCode=500;res.end(JSON.stringify({error:e.message}));}
  });
  server.listen(port,'127.0.0.1',()=>console.log(`LDH API http://127.0.0.1:${port}`));
  return server;
}
