// All visual content is data. Only these component shapes may enter the canvas.
export type VisualEvent =
  | { id: string; kind: 'summary'; title: string; text: string; assistant: 'jarvis' | 'tuki'; provenance: 'actual' | 'simulation' | 'placeholder' }
  | { id: string; kind: 'source'; title: string; url: string; text: string; provenance: 'actual' | 'simulation' | 'placeholder' }
  | { id: string; kind: 'comparison'; title: string; columns: string[]; rows: string[][]; provenance: 'actual' | 'simulation' | 'placeholder' }
  | { id: string; kind: 'progress'; title: string; value: number; provenance: 'actual' | 'simulation' | 'placeholder' };

const text = (x: unknown, max = 5000): x is string => typeof x === 'string' && x.length > 0 && x.length <= max;
const provenance = (x: unknown): x is VisualEvent['provenance'] => x === 'actual' || x === 'simulation' || x === 'placeholder';

export function validateVisualEvent(value: unknown): VisualEvent | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const x = value as Record<string, unknown>;
  if (!text(x.id, 100) || !/^[a-zA-Z0-9_-]+$/.test(x.id) || !text(x.title, 160) || !provenance(x.provenance)) return null;
  if (x.kind === 'summary' && text(x.text) && (x.assistant === 'jarvis' || x.assistant === 'tuki'))
    return { id: x.id, kind: 'summary', title: x.title, text: x.text, assistant: x.assistant, provenance: x.provenance };
  if (x.kind === 'source' && text(x.text) && text(x.url, 2048)) {
    try {
      const url = new URL(x.url);
      if (url.protocol !== 'https:' || url.username || url.password) return null;
      return { id: x.id, kind: 'source', title: x.title, text: x.text, url: url.href, provenance: x.provenance };
    } catch { return null; }
  }
  if (x.kind === 'progress' && typeof x.value === 'number' && Number.isFinite(x.value) && x.value >= 0 && x.value <= 100)
    return { id: x.id, kind: 'progress', title: x.title, value: x.value, provenance: x.provenance };
  if (x.kind === 'comparison' && Array.isArray(x.columns) && x.columns.length > 0 && x.columns.length <= 6 && x.columns.every(c => text(c, 160)) && Array.isArray(x.rows) && x.rows.length <= 30 && x.rows.every(row => Array.isArray(row) && row.length === (x.columns as unknown[]).length && row.every(cell => text(cell, 500))))
    return { id: x.id, kind: 'comparison', title: x.title, columns: x.columns, rows: x.rows, provenance: x.provenance };
  return null;
}

export const CANVAS_KEY = 'jarvis-intelligence-canvas-v1';
export function readCanvas(storage: Pick<Storage, 'getItem'>): VisualEvent[] {
  try {
    const raw = storage.getItem(CANVAS_KEY);
    if (!raw || raw.length > 300000) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(0, 40).map(validateVisualEvent).filter((e): e is VisualEvent => e !== null);
  } catch { return []; }
}
