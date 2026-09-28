export function askAITransportFailure(error: unknown): { code: string; message: string; status: number } {
  if (error instanceof Error && error.name === "TimeoutError") {
    return { code: "ASK_AI_BACKEND_TIMEOUT", message: "Ask AI timed out waiting for the local backend. Check that the API service is running, then retry.", status: 504 };
  }
  return { code: "ASK_AI_BACKEND_UNAVAILABLE", message: "Ask AI cannot reach the local backend. Start the API service, then retry; this is not an OpenAI-key error.", status: 502 };
}
