export const API = "/api/ade";

async function decode<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function getJson<T>(path: string): Promise<T> {
  return decode<T>(await fetch(`${API}${path}`, {
    cache: "no-store",
    headers: { accept: "application/json" },
  }));
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return decode<T>(await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  }));
}
