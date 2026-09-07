export class OllamaProvider {
  constructor({ baseUrl, model }) { this.baseUrl = baseUrl.replace(/\/$/, ''); this.model = model; }
  async chat({ messages, tools }) {
    const response = await fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model: this.model, messages, tools, stream: false })
    });
    if (!response.ok) throw new Error(`Ollama error ${response.status}: ${await response.text()}`);
    const data = await response.json();
    const calls = data.message?.tool_calls || [];
    return {
      content: data.message?.content || '',
      rawToolCalls: calls,
      toolCalls: calls.map(c => ({ name: c.function.name, arguments: c.function.arguments || {} }))
    };
  }
}
