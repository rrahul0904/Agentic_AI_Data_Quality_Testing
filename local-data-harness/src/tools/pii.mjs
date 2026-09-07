const patterns = [
  ['email', /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi],
  ['phone_us', /\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b/g],
  ['ssn', /\b\d{3}-\d{2}-\d{4}\b/g],
  ['ipv4', /\b(?:\d{1,3}\.){3}\d{1,3}\b/g],
  ['credit_card_like', /\b(?:\d[ -]*?){13,19}\b/g]
];
export const piiScan = {
  name: 'pii_scan', description: 'Scan text locally for common PII patterns before execution or logging.',
  parameters: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
  async execute({ text }) {
    const findings = [];
    for (const [category, regex] of patterns) {
      for (const match of String(text).matchAll(regex)) findings.push({ category, index: match.index, preview: mask(match[0]) });
    }
    return { summary: `${findings.length} potential PII finding(s).`, findings };
  }
};
function mask(value) { return value.length <= 4 ? '*'.repeat(value.length) : `${value.slice(0,2)}***${value.slice(-2)}`; }
