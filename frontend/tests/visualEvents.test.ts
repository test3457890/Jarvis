import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readCanvas, validateVisualEvent } from '../src/visualEvents.ts';

const common = { id: 'card_1', title: 'Evidence', provenance: 'actual' };

test('the canvas drops executable content and invalid links', () => {
  assert.equal(validateVisualEvent({ ...common, kind: 'source', text: 'link', url: 'javascript:alert(1)' }), null);
  assert.equal(validateVisualEvent({ ...common, kind: 'source', text: 'link', url: 'https://user:pass@example.org' }), null);
  assert.equal(validateVisualEvent({ ...common, kind: 'html', html: '<script>bad()</script>' }), null);
  assert.deepEqual(validateVisualEvent({ ...common, kind: 'summary', assistant: 'tuki', text: 'Checked', html: '<script>bad()</script>' }),
    { ...common, kind: 'summary', assistant: 'tuki', text: 'Checked' });
});

test('the canvas rejects invalid measurement and oversized table data', () => {
  assert.equal(validateVisualEvent({ ...common, kind: 'progress', value: Infinity }), null);
  assert.equal(validateVisualEvent({ ...common, kind: 'progress', value: 101 }), null);
  assert.equal(validateVisualEvent({ ...common, kind: 'comparison', columns: ['A'], rows: [['one', 'two']] }), null);
  assert.equal(validateVisualEvent({ ...common, kind: 'comparison', columns: ['A'], rows: Array.from({ length: 31 }, () => ['x']) }), null);
});

test('saved canvas restores only validated bounded cards', () => {
  assert.deepEqual(readCanvas({ getItem: () => '{bad' }), []);
  const good = { ...common, kind: 'progress', value: 45 };
  const restored = readCanvas({ getItem: () => JSON.stringify([good, { ...good, value: -1 }]) });
  assert.deepEqual(restored, [good]);
  assert.equal(readCanvas({ getItem: () => 'x'.repeat(300001) }).length, 0);
});
