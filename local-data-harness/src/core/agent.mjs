export class AgentRuntime {
  constructor({ provider, registry, store, config, cwd }) {
    this.provider = provider;
    this.registry = registry;
    this.store = store;
    this.config = config;
    this.cwd = cwd;
  }

  async run(prompt) {
    const sessionId = this.store.createSession({ prompt, mode: this.config.mode, provider: this.config.provider });
    const messages = [
      { role: 'system', content: this.systemPrompt() },
      { role: 'user', content: prompt }
    ];
    try {
      for (let turn = 0; turn < this.config.maxTurns; turn++) {
        const response = await this.provider.chat({ messages, tools: this.registry.specs(), cwd: this.cwd });
        this.store.logEvent(sessionId, 'model', response);
        if (!response.toolCalls?.length) {
          const answer = response.content || 'No response generated.';
          this.store.finishSession(sessionId, answer);
          return { sessionId, answer };
        }
        messages.push({ role: 'assistant', content: response.content || '', tool_calls: response.rawToolCalls || response.toolCalls });
        for (const call of response.toolCalls) {
          const started = Date.now();
          let result;
          try {
            result = await this.registry.execute(call.name, call.arguments, { cwd: this.cwd });
          } catch (error) {
            result = { error: error.message };
          }
          this.store.logTool(sessionId, call.name, call.arguments, result, Date.now() - started);
          messages.push({ role: 'tool', name: call.name, content: JSON.stringify(result) });
        }
      }
      const answer = `Stopped after ${this.config.maxTurns} turns.`;
      this.store.finishSession(sessionId, answer);
      return { sessionId, answer };
    } catch (error) {
      this.store.failSession(sessionId, error.message);
      throw error;
    }
  }

  systemPrompt() {
    return `You are Local Data Harness, a local-first data engineering agent.\nMode: ${this.config.mode}.\nPrefer deterministic tools over guessing. Never claim a tool result you did not receive.\nFor SQL, analyze safety before execution. Builder may modify local files; Analyst and Plan are read-only.`;
  }
}
