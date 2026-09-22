import { strict as assert } from "node:assert";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("AI provider settings are available under Settings and use a secret reference", async () => {
  const shell = await readFile(new URL("../app/DraftShell.tsx", import.meta.url), "utf8");
  const page = await readFile(new URL("../app/settings/ai/page.tsx", import.meta.url), "utf8");
  assert.match(shell, /AI provider/);
  assert.match(shell, /\/settings\/ai/);
  assert.match(page, /API key environment variable/);
  assert.match(page, /Do not paste the key here/);
  assert.match(page, /\/api\/ai-provider/);
  assert.match(page, /api_key_env/);
});
