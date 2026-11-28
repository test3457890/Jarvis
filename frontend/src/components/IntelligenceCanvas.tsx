import React, { useEffect, useState } from 'react';
import { CANVAS_KEY, readCanvas, validateVisualEvent, type VisualEvent } from '../visualEvents';

export const IntelligenceCanvas: React.FC<{ incoming: unknown }> = ({ incoming }) => {
  const [cards, setCards] = useState<VisualEvent[]>(() => readCanvas(window.localStorage));
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const item = validateVisualEvent(incoming);
    if (item) setCards(previous => [item, ...previous.filter(card => card.id !== item.id)].slice(0, 40));
  }, [incoming]);
  useEffect(() => {
    try { window.localStorage.setItem(CANVAS_KEY, JSON.stringify(cards)); }
    catch { setNotice('Browser storage is unavailable; this canvas will not reopen automatically.'); }
  }, [cards]);

  const move = (index: number, offset: number) => setCards(previous => {
    const next = [...previous];
    const target = index + offset;
    if (target < 0 || target >= next.length) return previous;
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  });
  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ version: 1, cards }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'jarvis-intelligence-canvas.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return <section className="cc-canvas" aria-label="Intelligence Canvas">
    <div className="cc-row cc-canvas-toolbar">
      <div><h2>Intelligence Canvas</h2><p className="cc-hint">Saved in this browser profile. Cards are data, never instructions or executable code.</p></div>
      <button type="button" onClick={exportJson}>Export JSON</button>
      <button type="button" onClick={() => setCards([])} disabled={!cards.length}>Clear canvas</button>
    </div>
    {notice && <p role="status">{notice}</p>}
    {!cards.length && <div className="cc-card">Verified assistant replies and structured visual events appear here when available.</div>}
    <div className="cc-canvas-grid">
      {cards.map((card, index) => <article className="cc-card" key={card.id}>
        <div className="cc-row" style={{ justifyContent: 'space-between' }}>
          <strong>{card.title}</strong><span className="cc-badge">{card.provenance}</span>
        </div>
        {card.kind === 'summary' && <p>{card.text} <span className="cc-hint">— {card.assistant.toUpperCase()}</span></p>}
        {card.kind === 'source' && <p>{card.text} <a href={card.url} target="_blank" rel="noopener noreferrer">Open source</a></p>}
        {card.kind === 'progress' && <div><progress value={card.value} max={100} aria-label={card.title} /> {card.value}%</div>}
        {card.kind === 'comparison' && <div className="cc-canvas-overflow"><table className="cc-table"><thead><tr>{card.columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead><tbody>{card.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>}
        <div className="cc-row cc-canvas-controls">
          <button type="button" aria-label={`Move ${card.title} earlier`} disabled={index === 0} onClick={() => move(index, -1)}>↑</button>
          <button type="button" aria-label={`Move ${card.title} later`} disabled={index === cards.length - 1} onClick={() => move(index, 1)}>↓</button>
          <button type="button" aria-label={`Remove ${card.title}`} onClick={() => setCards(previous => previous.filter(c => c.id !== card.id))}>Remove</button>
        </div>
      </article>)}
    </div>
  </section>;
};
