import readline from 'node:readline/promises';
import { stdin as input, stdout as output } from 'node:process';
export async function repl(app) {
  const rl=readline.createInterface({input,output});
  console.log(`Local Data Harness | provider=${app.config.provider} model=${app.config.model} mode=${app.config.mode}`);
  console.log('Commands: /help /tools /sessions /quit');
  while(true){
    const line=(await rl.question('ldh> ')).trim(); if(!line) continue;
    if(['/quit','/exit'].includes(line)) break;
    if(line==='/help'){ console.log('Try: discover | analyze models/orders.sql | lineage models/orders.sql | dbt inspect'); continue; }
    if(line==='/tools'){ console.table(app.registry.list().map(x=>({name:x.name,description:x.description}))); continue; }
    if(line==='/sessions'){ console.table(app.store.recent()); continue; }
    try { const r=await app.agent.run(line); console.log(r.answer); } catch(e){ console.error('Error:',e.message); }
  }
  rl.close();
}
