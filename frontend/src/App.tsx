import React, { useEffect, useState } from 'react';
import { api, subscribeEvents } from './api';
import { useCCStore, WORKSPACES, WorkspaceId } from './store';
import { WorkspaceView } from './components/Workspaces';
import { IntelligenceCanvas } from './components/IntelligenceCanvas';

export const App: React.FC = () => {
  const {
    workspace, setWorkspace, sidebarWidth, setSidebarWidth,
    fullscreen, toggleFullscreen, reducedMotion, toggleReducedMotion,
    floatingMode, toggleFloatingMode, paletteOpen, setPaletteOpen,
    coreStatus, activeAssistant, setCoreStatus, setAppState, addMessage, pendingApproval, setPendingApproval,
  } = useCCStore();
  const [palQuery, setPalQuery] = useState('');
  const [canvasOpen, setCanvasOpen] = useState(false);
  const [visualEvent, setVisualEvent] = useState<unknown>(null);

  useEffect(() => {
    api('/api/state').then(setAppState).catch(() => {});
    const unsub = subscribeEvents((ev) => {
      if (ev.kind === 'status') setCoreStatus(String(ev.data || 'idle'));
      else if (ev.kind === 'reply' && ev.data?.text) {
        const who = ev.data.assistant === 'tuki' ? 'tuki' : 'jarvis';
        setCoreStatus('idle', who);
        addMessage(who, ev.data.text);
        setVisualEvent({ id: `reply-${Date.now()}-${Math.random().toString(36).slice(2)}`, kind: 'summary', title: `${who.toUpperCase()} response`, text: ev.data.text, assistant: who, provenance: 'actual' });
      } else if (ev.kind === 'visual') {
        // Model-provided claims are unverified until a trusted producer supplies evidence.
        setVisualEvent({ ...ev.data, provenance: 'placeholder' });
      } else if (ev.kind === 'pending') {
        setPendingApproval(ev.data?.id ? { id: ev.data.id, summary: ev.data.text || 'Confirm action' } : null);
      }
    });
    return unsub;
  }, [setAppState, setCoreStatus, addMessage, setPendingApproval]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen(!paletteOpen);
      } else if (e.key === 'Escape' && paletteOpen) {
        setPaletteOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [paletteOpen, setPaletteOpen]);

  const groups: Array<'Core' | 'Intelligence' | 'Operations' | 'System'> = ['Core', 'Intelligence', 'Operations', 'System'];
  const filteredPal = WORKSPACES.filter((w) =>
    !palQuery || `${w.label} ${w.group} ${w.id}`.toLowerCase().includes(palQuery.toLowerCase()),
  );

  const startResize = (e: React.MouseEvent) => {
    e.preventDefault();
    const onMove = (mv: MouseEvent) => setSidebarWidth(mv.clientX);
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  return (
    <div className={`${reducedMotion ? 'cc-reduced-motion' : ''} ${floatingMode ? 'cc-floating' : ''}`}>
      <div className="cc-shell">
        <header className="cc-topbar">
          <div className="cc-brand">
            <div className={`cc-core ${activeAssistant}`} aria-hidden="true" />
            <span>JARVIS &amp; TUKI</span>
            <span className="cc-badge live">JARVIS: {activeAssistant === 'jarvis' ? coreStatus : 'ready'}</span>
            <span className="cc-badge sim">TUKI: {activeAssistant === 'tuki' ? coreStatus : 'standby'}</span>
          </div>
          <div className="cc-row">
            <button type="button" aria-pressed={canvasOpen} onClick={() => setCanvasOpen(open => !open)}>{canvasOpen ? 'Workspaces' : 'Intelligence Canvas'}</button>
            <button type="button" onClick={() => setPaletteOpen(true)} title="Command Palette (Ctrl+K)">Palette (Ctrl+K)</button>
            <button type="button" onClick={toggleFullscreen}>{fullscreen ? 'Show Rail' : 'Full Screen'}</button>
            <button type="button" onClick={toggleFloatingMode}>{floatingMode ? 'Dock Window' : 'Floating Mini'}</button>
            <button type="button" onClick={toggleReducedMotion}>{reducedMotion ? 'Motion: Reduced' : 'Motion: On'}</button>
            <a href="/" style={{ color: 'var(--cyan)', fontSize: 13, textDecoration: 'none', padding: '6px 10px', border: '1px solid var(--line)', borderRadius: 8 }}>Legacy HUD</a>
          </div>
        </header>

        {pendingApproval && (
          <div className="cc-card" role="alertdialog" aria-label="Action approval" style={{ borderColor: 'var(--warn)', margin: 8 }}>
            <strong>Action approval required:</strong> {pendingApproval.summary}
            <div className="cc-row" style={{ marginTop: 8 }}>
              <button className="primary" type="button" onClick={async () => {
                try {
                  const response = await api('/api/confirm', { yes: true, id: pendingApproval.id });
                  addMessage('system', typeof response.result === 'string' ? response.result : JSON.stringify(response.result));
                  setPendingApproval(null);
                }
                catch (e: any) { addMessage('system', e.message); }
              }}>Approve</button>
              <button className="danger" type="button" onClick={async () => {
                try { await api('/api/confirm', { yes: false, id: pendingApproval.id }); setPendingApproval(null); }
                catch (e: any) { addMessage('system', e.message); }
              }}>Deny</button>
            </div>
          </div>
        )}

        <div className="cc-body">
          {!fullscreen && !floatingMode && (
            <>
              <nav className="cc-rail" style={{ width: sidebarWidth }} aria-label="19 Command Center Workspaces">
                {groups.map((grp) => (
                  <div key={grp}>
                    <div className="cc-rail-group">{grp}</div>
                    {WORKSPACES.filter((w) => w.group === grp).map((w) => (
                      <button
                        key={w.id}
                        type="button"
                        data-cc-ws={w.id}
                        className={`cc-nav-btn ${workspace === w.id ? 'active' : ''}`}
                        onClick={() => setWorkspace(w.id)}
                      >
                        <span>{w.label}</span>
                        {w.shortcut && <span className="cc-hint">{w.shortcut}</span>}
                      </button>
                    ))}
                  </div>
                ))}
              </nav>
              <div className="cc-resizer" onMouseDown={startResize} role="separator" aria-orientation="vertical" aria-label="Resize sidebar" />
            </>
          )}

          <main className="cc-main">
            <div hidden={!canvasOpen}><IntelligenceCanvas incoming={visualEvent} /></div>
            {!canvasOpen && <WorkspaceView id={workspace} />
          </main>
        </div>
      </div>

      {paletteOpen && (
        <div className="cc-palette-backdrop" onClick={() => setPaletteOpen(false)}>
          <div className="cc-palette" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Command Palette">
            <input
              autoFocus
              value={palQuery}
              onChange={(e) => setPalQuery(e.target.value)}
              placeholder="Jump to any of the 19 workspaces…"
              style={{ width: '100%', marginBottom: 10 }}
            />
            <div className="cc-stack" style={{ maxHeight: 320, overflowY: 'auto' }}>
              {filteredPal.map((w) => (
                <button
                  key={w.id}
                  type="button"
                  onClick={() => { setWorkspace(w.id as WorkspaceId); setPaletteOpen(false); setPalQuery(''); }}
                  style={{ textAlign: 'left' }}
                >
                  {w.label} <span className="cc-hint">({w.group})</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
