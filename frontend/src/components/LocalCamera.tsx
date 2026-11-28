import React, { useCallback, useEffect, useRef, useState } from 'react';

// Browser media permissions are granted only after the user presses Start.
export const LocalCamera: React.FC<{ locked: boolean }> = ({ locked }) => {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const requestId = useRef(0);
  const lockedRef = useRef(locked);
  lockedRef.current = locked;
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState('');
  const [role, setRole] = useState('user');
  const [resolution, setResolution] = useState('640x480');
  const [fps, setFps] = useState(15);
  const [active, setActive] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [status, setStatus] = useState('Camera off. No frames are saved or sent.');
  const [snapshot, setSnapshot] = useState<string | null>(null);

  const stop = useCallback(() => {
    requestId.current += 1;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setActive(false);
    setRequesting(false);
    setSnapshot(null);
    setStatus('Camera off. No frames are saved or sent.');
  }, []);

  useEffect(() => {
    if (locked) stop();
  }, [locked, stop]);
  useEffect(() => () => {
    requestId.current += 1;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
  }, []);

  const start = async () => {
    if (locked || !navigator.mediaDevices?.getUserMedia) {
      setStatus(locked ? 'Lockdown blocks camera activation.' : 'Camera access is unavailable in this browser.');
      return;
    }
    stop();
    const currentRequest = requestId.current;
    setRequesting(true);
    setStatus('Waiting for browser camera permission…');
    try {
      const [width, height] = resolution.split('x').map(Number);
      const media = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}), width: { ideal: width }, height: { ideal: height }, frameRate: { ideal: fps, max: fps },
      } });
      if (lockedRef.current || currentRequest !== requestId.current) {
        media.getTracks().forEach(track => track.stop());
        return;
      }
      stream.current = media;
      if (video.current) video.current.srcObject = media;
      setActive(true);
      setRequesting(false);
      setStatus('LOCAL CAMERA ACTIVE. Browser preview only; use Stop to disconnect.');
      media.getVideoTracks().forEach(track => track.addEventListener('ended', stop, { once: true }));
      try {
        const available = await navigator.mediaDevices.enumerateDevices();
        if (currentRequest === requestId.current)
          setDevices(available.filter(item => item.kind === 'videoinput'));
      } catch { /* A failed device listing does not turn off an authorized preview. */ }
    } catch (error) {
      if (currentRequest !== requestId.current) return;
      stop();
      setStatus(error instanceof Error ? `Camera unavailable: ${error.name}` : 'Camera unavailable.');
    }
  };

  const capture = () => {
    if (!video.current || !stream.current || video.current.videoWidth === 0) return;
    const canvas = document.createElement('canvas');
    canvas.width = Math.min(video.current.videoWidth, 1280);
    canvas.height = Math.round(canvas.width * video.current.videoHeight / video.current.videoWidth);
    canvas.getContext('2d')?.drawImage(video.current, 0, 0, canvas.width, canvas.height);
    setSnapshot(canvas.toDataURL('image/png'));
    setStatus('One frame captured in browser memory. Stop clears it.');
  };

  return <section className="cc-card" aria-label="Local camera preview">
    <h3>Local Camera Preview</h3>
    <p className="cc-hint">Permission is requested only when you start. Video stays in this browser; no model analysis or network camera connection is enabled here.</p>
    <div className="cc-row" style={{ flexWrap: 'wrap' }}>
      <label>Role <select aria-label="Camera role" value={role} onChange={e => setRole(e.target.value)} disabled={active}>
        <option value="user">User facing</option><option value="workbench">Workbench</option>
      </select></label>
      <label>Device <select aria-label="Camera device" value={deviceId} onChange={e => setDeviceId(e.target.value)} disabled={active}>
        <option value="">Browser default</option>{devices.map(d => <option key={d.deviceId} value={d.deviceId}>{d.label || 'Authorized camera'}</option>)}
      </select></label>
      <label>Resolution <select aria-label="Camera resolution" value={resolution} onChange={e => setResolution(e.target.value)} disabled={active}>
        <option>640x480</option><option>1280x720</option>
      </select></label>
      <label>Frames per second <select aria-label="Camera frame rate" value={fps} onChange={e => setFps(Number(e.target.value))} disabled={active}>
        <option value={10}>10</option><option value={15}>15</option><option value={30}>30</option>
      </select></label>
      <button type="button" onClick={start} disabled={active || requesting || locked}>Start camera</button>
      <button type="button" onClick={stop} disabled={!active && !requesting}>Stop camera</button>
      <button type="button" onClick={capture} disabled={!active}>Capture frame</button>
    </div>
    <p role="status" aria-live="polite">{active && <span className="cc-badge live">CAMERA ON · {role}</span>} {status}</p>
    <video ref={video} autoPlay muted playsInline aria-label="Local camera live preview" style={{ display: active ? 'block' : 'none', maxWidth: '100%', maxHeight: 380 }} />
    {snapshot && <img src={snapshot} alt="Temporary captured frame from local camera" style={{ maxWidth: '100%', maxHeight: 240 }} />}
  </section>;
};
