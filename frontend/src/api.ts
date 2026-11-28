declare global {
  interface Window {
    __JARVIS_SESSION__?: string;
  }
}

export function sessionKey(): string {
  return window.__JARVIS_SESSION__ || '';
}

export async function api<T = any>(path: string, body?: Record<string, unknown>): Promise<T> {
  const headers: Record<string, string> = { 'X-Jarvis-Key': sessionKey() };
  const init: RequestInit = { method: body ? 'POST' : 'GET', headers };
  if (body) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data as T;
}

export function subscribeEvents(onEvent: (ev: { kind: string; data: any }) => void): () => void {
  const key = sessionKey();
  if (!key) return () => {};
  const es = new EventSource(`/api/events?key=${encodeURIComponent(key)}`);
  es.onmessage = (msg) => {
    try {
      const parsed = JSON.parse(msg.data);
      if (parsed && parsed.kind) onEvent(parsed);
    } catch {
      // ignore keep-alive or malformed lines
    }
  };
  return () => es.close();
}
