const modePolicy = {
  analyst: { fileWrite: false, sqlWrite: false, bash: false, externalWrite: false },
  plan: { fileWrite: false, sqlWrite: false, bash: false, externalWrite: false },
  builder: { fileWrite: true, sqlWrite: true, bash: false, externalWrite: true }
};

export class ToolRegistry {
  constructor(mode = 'analyst') {
    this.mode = mode;
    this.tools = new Map();
  }

  register(tool) { this.tools.set(tool.name, tool); return this; }
  list() { return [...this.tools.values()].map(({ execute, ...meta }) => meta); }
  specs() {
    return [...this.tools.values()].map(t => ({
      type: 'function',
      function: { name: t.name, description: t.description, parameters: t.parameters }
    }));
  }

  async execute(name, args = {}, context = {}) {
    const tool = this.tools.get(name);
    if (!tool) throw new Error(`Unknown tool: ${name}`);
    const policy = modePolicy[this.mode] ?? modePolicy.analyst;
    if (tool.capability && policy[tool.capability] === false) {
      throw new Error(`Tool '${name}' is blocked in ${this.mode} mode`);
    }
    return await tool.execute(args, { ...context, mode: this.mode });
  }
}
