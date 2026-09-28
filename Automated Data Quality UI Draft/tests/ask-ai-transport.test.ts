import assert from "node:assert/strict";
import test from "node:test";

import { askAITransportFailure } from "../lib/ask-ai-transport.ts";

test("a refused backend connection is not reported as an OpenAI-key failure", () => {
  const failure = askAITransportFailure(new TypeError("fetch failed"));
  assert.equal(failure.status, 502);
  assert.equal(failure.code, "ASK_AI_BACKEND_UNAVAILABLE");
  assert.match(failure.message, /local backend/);
  assert.doesNotMatch(failure.message, /fetch failed/);
});

test("a bounded timeout has its own status", () => {
  const error = new Error("The operation was aborted");
  error.name = "TimeoutError";
  const failure = askAITransportFailure(error);
  assert.equal(failure.status, 504);
  assert.equal(failure.code, "ASK_AI_BACKEND_TIMEOUT");
});
