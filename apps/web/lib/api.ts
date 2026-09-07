export const API = process.env.NEXT_PUBLIC_ADE_API_URL ?? "http://127.0.0.1:8001";

async function decode<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function getJson<T>(path: string): Promise<T> {
  return decode<T>(await fetch(`${API}${path}`, { cache: "no-store" }));
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return decode<T>(await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }));
}
