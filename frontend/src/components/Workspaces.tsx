import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { useCCStore, WorkspaceId } from '../store';
import { Globe3D } from './Globe3D';
import { LocalCamera } from './LocalCamera';

export const WorkspaceView: React.FC<{ id: WorkspaceId }> = ({ id }) => {
  const { messages, addMessage, vitals, setVitals, appState } = useCCStore();
  const [input, setInput] = useState('');
  const [data, setData] = useState<any>(null);
  const [statusMsg, setStatusMsg] = useState('');
  const [search, setSearch] = useState('');

  // Load workspace-specific live backend data on demand (lazy loading per Phase 12!)
  useEffect(() => {
    let active = true;
    setData(null);
    setStatusMsg('');
    const map: Partial<Record<WorkspaceId, string>> = {
      computer: '/api/uia',
      sentinel: '/api/sentinel-ops',
      agents: '/api/coop-agents',
      automation: '/api/coop-agents',
      smarthome: '/api/smarthome',
      containers: '/api/containers',
      voice: '/api/voice-studio',
      models: '/api/providers',
      connections: '/api/catalogue',
      professional: '/api/office',
      academic: '/api/office',
      research: '/api/office',
      developer: '/api/tools/catalogue',
      communications: '/api/connections',
      audit: '/api/activity',
      repair: '/api/recovery',
      settings: '/api/setup',
    };
    const ep = map[id];
    if (ep) {
      api(ep)
        .then((res) => { if (active) setData(res); })
        .catch((e) => { if (active) setStatusMsg(e.message); });
    }
    return () => { active = false; };
  }, [id]);

  const sendChat = async () => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    addMessage('user', text);
    try {
      await api('/api/chat', { text });
    } catch (e: any) {
      addMessage('system', e.message);
    }
  };

  const refreshVitals = async () => {
    try {
      const v = await api('/api/vitals');
      setVitals(v);
    } catch (e: any) {
      setStatusMsg(e.message);
    }
  };

  if (id === 'console') {
    const cpu = vitals?.cpu?.percent;
    const ram = vitals?.memory?.percent;
    const gpu = vitals?.gpus?.[0];
    return (
      <div className="cc-stack">
        <div className="cc-grid">
          <div className="cc-card">
            <strong>CPU Load (Live)</strong>
            <div style={{ fontSize: 22, color: 'var(--cyan)' }}>{cpu != null ? `${cpu}%` : 'Click Refresh'}</div>
          </div>
          <div className="cc-card">
            <strong>Memory Usage (Live)</strong>
            <div style={{ fontSize: 22, color: 'var(--cyan)' }}>{ram != null ? `${ram}%` : 'Click Refresh'}</div>
          </div>
          <div className="cc-card">
            <strong>GPU / VRAM (Live)</strong>
            <div style={{ fontSize: 16, color: 'var(--tuki)' }}>
              {gpu ? `${gpu.name} · ${gpu.vram_used_gb}/${gpu.vram_total_gb} GB` : 'Not sampled yet'}
            </div>
          </div>
          <div className="cc-card">
            <strong>Security Posture</strong>
            <div className="cc-hint">
              Lockdown: {appState.lockdown ? 'ON' : 'OFF'} · Internet: {appState.allow_internet_tools ? 'ON' : 'OFF'}
            </div>
            <button type="button" onClick={refreshVitals}>Refresh Live Vitals</button>
          </div>
        </div>

        <div className="cc-card" style={{ maxHeight: 300, overflowY: 'auto' }}>
          {messages.map((m) => (
            <div key={m.id} style={{ marginBottom: 8 }}>
              <span className="cc-badge" style={{ marginRight: 6 }}>{m.role.toUpperCase()}</span>
              <span>{m.text}</span>
              <span className="cc-hint" style={{ marginLeft: 8 }}>{m.ts}</span>
            </div>
          ))}
        </div>

        <div className="cc-row">
          <input
            style={{ flex: 1 }}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') sendChat(); }}
            placeholder="Command Jarvis or TUKI (e.g. 'TUKI verify this', '/calc 2+2', '/status')…"
            aria-label="Command Console input"
          />
          <button className="primary" type="button" onClick={sendChat}>Send</button>
          <button className="danger" type="button" onClick={() => api('/api/stop', {})}>Stop</button>
        </div>

        {(vitals?.processes?.length ?? 0) > 0 && (
          <div className="cc-card">
            <strong>Live Process Radar (Top Local Processes)</strong>
            <table className="cc-table">
              <thead><tr><th>PID</th><th>Name</th><th>CPU %</th><th>Mem MB</th></tr></thead>
              <tbody>
                {(vitals?.processes || []).slice(0, 8).map((p: any) => (
                  <tr key={p.pid}><td>{p.pid}</td><td>{p.name}</td><td>{p.cpu_percent}</td><td>{p.memory_mb}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  if (id === 'globe') {
    return (
      <div className="cc-card">
        <h3>Global Intelligence Command Center (3D Globe)</h3>
        <Globe3D />
      </div>
    );
  }

  if (id === 'computer') {
    return (
      <div className="cc-stack">
        <div className="cc-card">
          <h3>Computer Control (Windows UI Automation &amp; Accessibility Tree)</h3>
          <p className="cc-hint">Accessibility-first automation. Password fields, authentication forms, and UAC prompts are strictly blocked.</p>
          <div className="cc-row">
            <button className="primary" type="button" onClick={async () => {
              const r = await api('/api/uia', { action: 'inspect', window: '' });
              setStatusMsg(`Inspected '${r.window || 'none'}': ${(r.nodes || []).length} accessible controls.`);
            }}>Inspect Active Window UIA Tree</button>
            <button className="danger" type="button" onClick={async () => {
              await api('/api/uia', { action: 'cancel' });
              setStatusMsg('Emergency manual takeover triggered.');
            }}>Emergency Takeover / Cancel</button>
          </div>
          {statusMsg && <p className="cc-hint" role="status">{statusMsg}</p>}
        </div>
        <div className="cc-card">
          <strong>Visible Desktop Windows ({data?.windows?.length ?? 0})</strong>
          <ul>{(data?.windows || []).slice(0, 15).map((w: any) => <li key={w.hwnd}>{w.title}</li>)}</ul>
        </div>
      </div>
    );
  }

  if (id === 'sentinel') {
    return (
      <div className="cc-stack">
        <div className="cc-card">
          <h3>Sentinel Defensive Cybersecurity Workspace</h3>
          <p className="cc-hint">Defensive monitoring, FIM, secret scanning, firewall dry-run previews, and evidence export only.</p>
          <div className="cc-row">
            <button className="primary" type="button" onClick={async () => {
              const r = await api('/api/sentinel-ops', { action: 'fim_verify' });
              setStatusMsg(`FIM Verify: intact=${r.intact}, modified=${r.modified.length}, missing=${r.missing.length}`);
            }}>Verify FIM Baselines</button>
            <button type="button" onClick={async () => {
              const r = await api('/api/sentinel-ops', { action: 'firewall_preview', name: 'BlockTest', remote_ip: '203.0.113.10' });
              setStatusMsg(`Dry-Run Preview: ${r.command_preview}`);
            }}>Preview Defensive Firewall Rule</button>
            <button type="button" onClick={async () => {
              const r = await api('/api/sentinel-ops', { action: 'export_evidence', title: 'hud_snapshot' });
              setStatusMsg(`Evidence exported (${r.bytes} B · SHA-256 ${r.sha256.slice(0, 16)}…)`);
            }}>Export Incident Evidence Pack</button>
          </div>
          {statusMsg && <p className="cc-hint" role="status">{statusMsg}</p>}
        </div>
        <div className="cc-card">
          <strong>Optional Defensive Integrations (Wazuh, Suricata, Zeek, YARA, Velociraptor, Trivy)</strong>
          <table className="cc-table">
            <thead><tr><th>Tool</th><th>Role</th><th>License</th><th>Local Status</th></tr></thead>
            <tbody>
              {(data?.integrations || []).map((t: any) => (
                <tr key={t.id}><td>{t.id}</td><td>{t.role}</td><td>{t.license}</td><td>{t.installed ? 'Installed' : 'Optional (not installed)'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (id === 'containers') {
    return (
      <div className="cc-stack">
        <div className="cc-card">
          <h3>Container &amp; Isolated Execution Management</h3>
          <p className="cc-hint">Docker CLI: {data?.docker?.cli_installed ? 'Installed' : 'Missing'} · Daemon: {data?.docker?.daemon_running ? `Running (${data.docker.version})` : data?.docker?.reason || 'Stopped'}</p>
          <button className="primary" type="button" onClick={async () => {
            const r = await api('/api/containers', { action: 'preview_run', image: 'python:3.12-slim', command: ['python', '-V'] });
            setStatusMsg(`Hardened Preview: ${(r.command || []).join(' ')}`);
          }}>Preview Hardened Sandbox Command</button>
          {statusMsg && <p className="cc-hint" role="status">{statusMsg}</p>}
          <p className="cc-hint">Enforced invariants: non-root (65534:65534), --read-only, --cap-drop=ALL, --network=none, docker.sock &amp; --privileged strictly prohibited.</p>
        </div>
      </div>
    );
  }

  if (id === 'smarthome') {
    return (
      <div className="cc-stack">
        <LocalCamera locked={Boolean(appState.lockdown)} />
        <div className="cc-card">
          <h3>Smart Home &amp; Authorized Camera Center</h3>
          <p className="cc-hint">Owner-authorized Home Assistant, ONVIF, RTSP, Frigate NVR, and public weather/traffic webcams only. DPAPI credentials; facial ID prohibited.</p>
          <p className="cc-hint">Registered authorized devices: {(data?.devices || []).length} · Recent events: {(data?.events || []).length}</p>
        </div>
      </div>
    );
  }

  if (id === 'agents' || id === 'automation') {
    return (
      <div className="cc-card">
        <h3>{id === 'agents' ? 'Cooperative Jarvis & TUKI Agent Center' : 'Visual Automation Builder'}</h3>
        <p className="cc-hint">Bounded recursion depth (max {data?.limits?.max_recursion_depth ?? 3}) · Persistent checkpoints · Approval gates.</p>
        <div className="cc-row">
          <button className="primary" type="button" onClick={async () => {
            const r = await api('/api/coop-agents', {
              action: 'create_plan',
              title: 'Jarvis + TUKI Verification Plan',
              goal: 'Research and verify local system state',
              steps: [
                { id: 's1', title: 'TUKI Independent Research', agent: 'tuki_research' },
                { id: 's2', title: 'Jarvis Coordinator Summary', agent: 'jarvis_coordinator', depends_on: ['s1'] },
              ],
            });
            setData(r.workspace);
            setStatusMsg(`Created cooperative plan ${r.plan.id}`);
          }}>New Cooperative Plan</button>
        </div>
        {statusMsg && <p className="cc-hint" role="status">{statusMsg}</p>}
        <p className="cc-hint">Active plans: {(data?.plans || []).length} · Saved visual automations: {(data?.automations || []).length}</p>
      </div>
    );
  }

  if (id === 'voice') {
    const rt = data?.runtime || {};
    return (
      <div className="cc-card">
        <h3>Voice Studio (Neural TTS · CUDA GPU / CPU)</h3>
        <p className="cc-hint">
          Runtime: {rt.ok ? `Python ${rt.python} READY (${rt.cuda_available ? 'CUDA GPU' : 'CPU'})` : 'Loading…'} ·
          Providers: {(rt.ort_providers || []).join(', ')}
        </p>
        <div className="cc-row">
          <button className="primary" type="button" onClick={async () => {
            setStatusMsg('Synthesizing Jarvis neural preview…');
            const r = await api('/api/voice-studio', { action: 'preview', assistant: 'jarvis', speak: false });
            setStatusMsg(`Jarvis (${r.engine}/${r.voice} · ${r.actual_provider}): ${r.audio_seconds}s in ${r.total_seconds}s (RTF ${r.rtf})`);
          }}>Preview Jarvis</button>
          <button type="button" onClick={async () => {
            setStatusMsg('Synthesizing TUKI neural preview…');
            const r = await api('/api/voice-studio', { action: 'preview', assistant: 'tuki', speak: false });
            setStatusMsg(`TUKI (${r.engine}/${r.voice} · ${r.actual_provider}): ${r.audio_seconds}s in ${r.total_seconds}s (RTF ${r.rtf})`);
          }}>Preview TUKI</button>
          <button className="danger" type="button" onClick={async () => {
            await api('/api/voice-studio', { action: 'cancel' });
            setStatusMsg('Cancelled active neural speech synthesis.');
          }}>Cancel Speech</button>
        </div>
        {statusMsg && <p className="cc-hint" role="status">{statusMsg}</p>}
      </div>
    );
  }

  if (id === 'connections') {
    const items = (data?.items || []).filter((it: any) =>
      !search || `${it.name} ${it.category} ${it.license}`.toLowerCase().includes(search.toLowerCase()),
    );
    return (
      <div className="cc-card">
        <h3>Connections &amp; Searchable MCP Catalogue</h3>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search vetted MCP servers & connectors…" style={{ width: '100%', marginBottom: 10 }} />
        <table className="cc-table">
          <thead><tr><th>Connector</th><th>Category</th><th>License</th><th>Security Review</th></tr></thead>
          <tbody>
            {items.map((it: any) => (
              <tr key={it.id}><td>{it.name}</td><td>{it.category}</td><td>{it.license}</td><td>{it.security_review}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (id === 'developer') {
    const tools = (data?.tools || []).filter((t: any) =>
      !search || `${t.name} ${t.description}`.toLowerCase().includes(search.toLowerCase()),
    );
    return (
      <div className="cc-card">
        <h3>Developer Center &amp; Searchable Tool Catalogue ({tools.length} Live Skills)</h3>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search registered Jarvis skills & risk tiers…" style={{ width: '100%', marginBottom: 10 }} />
        <table className="cc-table">
          <thead><tr><th>Skill</th><th>Tier</th><th>Description</th></tr></thead>
          <tbody>
            {tools.slice(0, 30).map((t: any) => (
              <tr key={t.name}><td><code>{t.name}</code></td><td><span className="cc-badge">{t.tier}</span></td><td>{t.description}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (id === 'professional' || id === 'academic' || id === 'research') {
    return (
      <div className="cc-card">
        <h3>{id === 'professional' ? 'Professional & Office Documents' : id === 'academic' ? 'Academic Center & Citations' : 'Research & Knowledge Graph'}</h3>
        <p className="cc-hint">Local OOXML .docx/.pptx export, BibTeX/APA citations, and SQLite Knowledge Graph (Finance/Health boundaries preserved).</p>
        <div className="cc-row">
          <button className="primary" type="button" onClick={async () => {
            const r = await api('/api/office', { action: 'generate_docx', filename: 'jarvis_brief.docx', title: 'Jarvis Executive Brief', paragraphs: ['Generated 100% locally.'] });
            setStatusMsg(`Generated DOCX (${r.bytes} bytes) at ${r.path}`);
          }}>Generate Local DOCX</button>
          <button type="button" onClick={async () => {
            const r = await api('/api/office', { action: 'generate_pptx', filename: 'jarvis_deck.pptx', slides: [{ title: 'Jarvis & TUKI', body: 'Local Command Center Briefing' }] });
            setStatusMsg(`Generated PPTX (${r.slides} slides, ${r.bytes} bytes)`);
          }}>Generate Local PPTX</button>
        </div>
        {statusMsg && <p className="cc-hint" role="status">{statusMsg}</p>}
        <p className="cc-hint">Saved Citations: {(data?.citations || []).length} · Knowledge Graph Edges: {(data?.knowledge_graph || []).length}</p>
      </div>
    );
  }

  return (
    <div className="cc-card">
      <h3 style={{ textTransform: 'capitalize' }}>{id} Workspace</h3>
      <p className="cc-hint">Connected to live Jarvis loopback backend. Status: {data ? 'Synchronized' : 'Loading…'}</p>
      {statusMsg && <p className="cc-hint" role="status">{statusMsg}</p>}
      <pre style={{ fontSize: 11.5, maxHeight: 360, overflow: 'auto', background: '#07101d', padding: 10, borderRadius: 8 }}>
        {JSON.stringify(data || {}, null, 2)}
      </pre>
    </div>
  );
};
