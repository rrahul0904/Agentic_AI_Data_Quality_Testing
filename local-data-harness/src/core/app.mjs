import { loadConfig } from '../config.mjs';
import { createRegistry } from '../tools/index.mjs';
import { SessionStore } from '../storage/session-store.mjs';
import { MockProvider } from '../providers/mock.mjs';
import { OllamaProvider } from '../providers/ollama.mjs';
import { AgentRuntime } from './agent.mjs';
export function createApp({ cwd=process.cwd(), overrides={} }={}) {
  const config=loadConfig(cwd,overrides); const registry=createRegistry(config.mode); const store=new SessionStore(cwd,config.dbPath);
  const provider=config.provider==='ollama' ? new OllamaProvider({baseUrl:config.ollamaUrl,model:config.model}) : new MockProvider();
  const agent=new AgentRuntime({provider,registry,store,config,cwd}); return {config,registry,store,agent};
}
