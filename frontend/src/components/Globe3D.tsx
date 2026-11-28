import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api';

interface Marker {
  lat: number;
  lon: number;
  label: string;
  data_class?: string;
}

export const Globe3D: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [rotLon, setRotLon] = useState(-95);
  const [rotLat, setRotLat] = useState(28);
  const [zoom, setZoom] = useState(1.0);
  const [status, setStatus] = useState<any>(null);
  const [markers, setMarkers] = useState<Marker[]>([]);
  const [sarPoints, setSarPoints] = useState<{ lat: number; lon: number }[]>([]);
  const [orbitStep, setOrbitStep] = useState(0);
  const [voiceCmd, setVoiceCmd] = useState('');
  const [noteLabel, setNoteLabel] = useState('');
  const [noteLat, setNoteLat] = useState('39.7392');
  const [noteLon, setNoteLon] = useState('-104.9903');
  const [msg, setMsg] = useState('3D Globe ready (offline geodesy + public feeds when Internet is ON).');

  const refresh = async () => {
    try {
      const st = await api('/api/geospatial');
      setStatus(st);
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const r = Math.min(w, h) * 0.42 * zoom;

    ctx.clearRect(0, 0, w, h);
    // Deep space backdrop
    const bg = ctx.createRadialGradient(cx, cy, r * 0.1, cx, cy, r * 1.3);
    bg.addColorStop(0, '#0c2238');
    bg.addColorStop(1, '#050b14');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    // Orthographic sphere projection
    const lam0 = (rotLon * Math.PI) / 180;
    const phi0 = (rotLat * Math.PI) / 180;
    const project = (lat: number, lon: number) => {
      const phi = (lat * Math.PI) / 180;
      const lam = (lon * Math.PI) / 180;
      const cosC = Math.sin(phi0) * Math.sin(phi) + Math.cos(phi0) * Math.cos(phi) * Math.cos(lam - lam0);
      if (cosC < 0) return null;
      const x = cx + r * Math.cos(phi) * Math.sin(lam - lam0);
      const y = cy - r * (Math.cos(phi0) * Math.sin(phi) - Math.sin(phi0) * Math.cos(phi) * Math.cos(lam - lam0));
      return { x, y };
    };

    // Globe sphere outline
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = '#081829';
    ctx.fill();
    ctx.strokeStyle = '#2ee6ff';
    ctx.lineWidth = 1.6;
    ctx.stroke();

    // Graticule grid
    ctx.strokeStyle = 'rgba(46, 230, 255, 0.16)';
    ctx.lineWidth = 0.8;
    for (let lat = -60; lat <= 60; lat += 30) {
      ctx.beginPath();
      let started = false;
      for (let lon = -180; lon <= 180; lon += 6) {
        const pt = project(lat, lon);
        if (pt) {
          if (!started) { ctx.moveTo(pt.x, pt.y); started = true; } else ctx.lineTo(pt.x, pt.y);
        } else { started = false; }
      }
      ctx.stroke();
    }
    for (let lon = -180; lon < 180; lon += 30) {
      ctx.beginPath();
      let started = false;
      for (let lat = -84; lat <= 84; lat += 6) {
        const pt = project(lat, lon);
        if (pt) {
          if (!started) { ctx.moveTo(pt.x, pt.y); started = true; } else ctx.lineTo(pt.x, pt.y);
        } else { started = false; }
      }
      ctx.stroke();
    }

    // Estimated ISS orbital track
    const orbitPts = status?.sample_orbital_track?.points || [];
    if (orbitPts.length) {
      ctx.strokeStyle = 'rgba(255, 180, 60, 0.75)';
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      let started = false;
      for (const op of orbitPts) {
        const pt = project(op.lat, op.lon);
        if (pt) {
          if (!started) { ctx.moveTo(pt.x, pt.y); started = true; } else ctx.lineTo(pt.x, pt.y);
        } else { started = false; }
      }
      ctx.stroke();
      const cur = orbitPts[orbitStep % orbitPts.length];
      const satPt = cur ? project(cur.lat, cur.lon) : null;
      if (satPt) {
        ctx.fillStyle = '#ffb43c';
        ctx.beginPath();
        ctx.arc(satPt.x, satPt.y, 4.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.font = '11px monospace';
        ctx.fillText('ISS (EST)', satPt.x + 7, satPt.y + 3);
      }
    }

    // SAR Grid (Simulated)
    if (sarPoints.length > 1) {
      ctx.strokeStyle = '#4ade80';
      ctx.lineWidth = 2;
      ctx.beginPath();
      let started = false;
      for (const sp of sarPoints) {
        const pt = project(sp.lat, sp.lon);
        if (pt) {
          if (!started) { ctx.moveTo(pt.x, pt.y); started = true; } else ctx.lineTo(pt.x, pt.y);
        } else { started = false; }
      }
      ctx.stroke();
    }

    // User annotations + public feed markers
    const allMarks: Marker[] = [
      ...(status?.annotations || []),
      ...markers,
    ];
    for (const m of allMarks) {
      const pt = project(m.lat, m.lon);
      if (!pt) continue;
      ctx.fillStyle = m.data_class === 'user_annotation' ? '#c084fc' : '#ff5f6d';
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#e2f4ff';
      ctx.font = '10px sans-serif';
      ctx.fillText(m.label.slice(0, 26), pt.x + 6, pt.y - 3);
    }
  }, [rotLon, rotLat, zoom, status, markers, sarPoints, orbitStep]);

  const loadFeed = async (feedId: string) => {
    setMsg(`Fetching public feed ${feedId}…`);
    try {
      const res = await api('/api/geospatial', { action: 'feed', feed_id: feedId });
      setMarkers(res.markers || []);
      setMsg(`${res.label} [${String(res.data_class).toUpperCase()}]: ${res.item_count} items · ${res.attribution}`);
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const plotSar = async () => {
    try {
      const res = await api('/api/geospatial', {
        action: 'sar_grid',
        lat: parseFloat(noteLat) || 39.7392,
        lon: parseFloat(noteLon) || -104.9903,
        radius_km: 15,
        spacing_km: 3,
      });
      setSarPoints(res.waypoints || []);
      setRotLat(res.center.lat);
      setRotLon(res.center.lon);
      setMsg(`SAR Grid [SIMULATED]: ${res.tracks} tracks, ${res.area_km2} km² · ${res.operational_limitations}`);
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const addNote = async () => {
    if (!noteLabel.trim()) return;
    try {
      await api('/api/geospatial', {
        action: 'add_annotation',
        label: noteLabel,
        lat: parseFloat(noteLat) || 39.7392,
        lon: parseFloat(noteLon) || -104.9903,
      });
      setNoteLabel('');
      await refresh();
      setMsg('Saved user map annotation.');
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const runVoiceNav = async () => {
    try {
      const res = await api('/api/geospatial', { action: 'voice_nav', command: voiceCmd });
      if (res.action === 'fly_to') {
        setRotLat(res.lat);
        setRotLon(res.lon);
        setMsg(`Navigated globe to ${res.label} (${res.lat}, ${res.lon}).`);
      } else if (res.action === 'toggle_layer' && res.feed) {
        await loadFeed(res.feed);
      } else {
        setMsg(res.message || 'Navigation command parsed.');
      }
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  return (
    <div className="cc-stack">
      <div className="cc-row">
        <span className="cc-badge live">LIVE: USGS / NWS</span>
        <span className="cc-badge delayed">DELAYED: OpenSky / NASA / NOAA</span>
        <span className="cc-badge est">ESTIMATED: Orbital Tracks</span>
        <span className="cc-badge sim">SIMULATED: SAR Grid</span>
      </div>
      <div className="cc-globe-wrap">
        <canvas ref={canvasRef} width={680} height={360} className="cc-globe-canvas" aria-label="3D Global Intelligence Globe" />
        <div className="cc-globe-controls">
          <label>Lon {rotLon}° <input type="range" min={-180} max={180} value={rotLon} onChange={(e) => setRotLon(Number(e.target.value))} /></label>
          <label>Lat {rotLat}° <input type="range" min={-80} max={80} value={rotLat} onChange={(e) => setRotLat(Number(e.target.value))} /></label>
          <label>Zoom {zoom.toFixed(1)}x <input type="range" min={0.7} max={2.0} step={0.1} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} /></label>
          <label>Timeline Frame {orbitStep} <input type="range" min={0} max={35} value={orbitStep} onChange={(e) => setOrbitStep(Number(e.target.value))} /></label>
        </div>
      </div>
      <div className="cc-row">
        <input value={voiceCmd} onChange={(e) => setVoiceCmd(e.target.value)} placeholder="Voice nav: 'fly to Tokyo', '39.7, -105.0', 'show earthquakes'" />
        <button type="button" onClick={runVoiceNav}>Navigate</button>
        <button type="button" onClick={plotSar}>Plot SAR Grid (Simulated)</button>
      </div>
      <div className="cc-row">
        <input value={noteLabel} onChange={(e) => setNoteLabel(e.target.value)} placeholder="Annotation label" />
        <input value={noteLat} onChange={(e) => setNoteLat(e.target.value)} style={{ maxWidth: 110 }} aria-label="Latitude" />
        <input value={noteLon} onChange={(e) => setNoteLon(e.target.value)} style={{ maxWidth: 110 }} aria-label="Longitude" />
        <button type="button" onClick={addNote}>Add Annotation</button>
      </div>
      <div className="cc-row">
        {(status?.feeds || []).map((f: any) => (
          <button key={f.id} type="button" onClick={() => loadFeed(f.id)} title={`${f.attribution} · ${f.freshness}`}>
            {f.label} ({f.data_class})
          </button>
        ))}
      </div>
      <p className="cc-hint" role="status">{msg}</p>
    </div>
  );
};
