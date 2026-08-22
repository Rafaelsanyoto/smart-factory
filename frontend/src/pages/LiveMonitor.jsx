import { useState, useEffect, useRef } from 'react';
import {
  Camera, ShieldAlert, CheckCircle, XCircle, MapPin, AlertTriangle,
  Video, Flame, Bot, ScanLine, Pause, Play,
} from 'lucide-react';

const API_BASE = 'http://127.0.0.1:8000';

const CAMERA_REGISTRY = [
  { id: 'stream_01', label: 'Assembly Line A (Cam 01)' },
  { id: 'stream_02', label: 'Welding Bay B (Cam 02)' },
];

const EMERGENCY_LABELS = ['FIRE', 'SMOKE'];

// Color intent for a detection label — keeps the command-center semantics consistent.
function labelTone(label) {
  if (label.includes('NO-')) return 'text-red-400 border-red-800/40 bg-red-950/40';
  if (EMERGENCY_LABELS.includes(label)) return 'text-orange-400 border-orange-800/40 bg-orange-950/40';
  if (label === 'PERSON') return 'text-slate-300 border-slate-700 bg-slate-800/40';
  return 'text-emerald-400 border-emerald-800/40 bg-emerald-950/30';
}

export default function LiveMonitor({ pendingIncidents = [], setPendingIncidents, verifiedIncidents = [], setVerifiedIncidents }) {
  const [activeStream, setActiveStream] = useState('stream_01');
  const [allDetections, setAllDetections] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [emergencyActive, setEmergencyActive] = useState(false);
  const [paused, setPaused] = useState(false);

  const seenEventIds = useRef(new Set());
  const audioCtxRef = useRef(null);
  const lastBeepRef = useRef(0);

  const playAlarm = () => {
    const now = Date.now();
    if (now - lastBeepRef.current < 1500) return; // throttle
    lastBeepRef.current = now;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      const ctx = audioCtxRef.current || (audioCtxRef.current = new Ctx());
      if (ctx.state === 'suspended') ctx.resume();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'square';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.setValueAtTime(660, ctx.currentTime + 0.18);
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.14, ctx.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.36);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.37);
    } catch {
      /* audio not available */
    }
  };

  // Live detection feed for the currently viewed stream (breakdown + stat + emergency banner)
  useEffect(() => {
    setAllDetections([]);
    setEmergencyActive(false);
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/data/${activeStream}`);
        const data = await res.json();
        if (data.status !== 'success' || !Array.isArray(data.detections)) return;

        setPaused(!!data.paused);

        const parsed = data.detections.map((d) => ({
          ...d,
          label: (d.class_name || d.name || d.class || '').toUpperCase(),
        }));
        setAllDetections(parsed);

        const hasEmergency = parsed.some((d) => EMERGENCY_LABELS.includes(d.label));
        setEmergencyActive(hasEmergency);
        if (hasEmergency && !data.paused) playAlarm();
      } catch (err) {
        console.error('Data polling error:', err);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [activeStream]);

  // Backend rule-engine events → verification queue (all streams, already deduped server-side)
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const [evtRes, notifRes] = await Promise.all([
          fetch(`${API_BASE}/api/events`),
          fetch(`${API_BASE}/api/notifications`),
        ]);
        const evtData = await evtRes.json();
        const notifData = await notifRes.json();

        if (notifData.status === 'success') setNotifications(notifData.notifications || []);

        if (evtData.status === 'success' && Array.isArray(evtData.events)) {
          const fresh = evtData.events.filter((e) => !seenEventIds.current.has(e.id));
          if (fresh.length > 0) {
            fresh.forEach((e) => seenEventIds.current.add(e.id));
            const mapped = fresh.map((e) => ({
              id: e.id,
              time: e.timestamp,
              type: (e.class || '').toUpperCase(),
              zone: e.zone,
              eventType: e.type, // VIOLATION | EMERGENCY
            }));
            if (typeof setPendingIncidents === 'function') {
              setPendingIncidents((prev) => [...mapped, ...prev].slice(0, 12));
            }
          }
        }
      } catch (err) {
        console.error('Event polling error:', err);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [setPendingIncidents]);

  const togglePause = async () => {
    const next = !paused;
    setPaused(next); // optimistic
    try {
      await fetch(`${API_BASE}/api/stream/${activeStream}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paused: next }),
      });
    } catch {
      setPaused(!next); // revert on failure
    }
  };

  const handleVerifyIncident = (id, status) => {
    const target = pendingIncidents.find((inc) => inc.id === id);
    if (!target) return;
    setPendingIncidents((prev) => prev.filter((inc) => inc.id !== id));
    if (status === 'CONFIRMED') {
      setVerifiedIncidents((prev) => [{ ...target, status: 'CONFIRMED' }, ...prev]);
    }
  };

  // Derived views
  const violationCount = allDetections.filter((d) => d.label.includes('NO-')).length;
  const breakdown = Object.values(
    allDetections.reduce((acc, d) => {
      const name = d.class_name || d.label;
      if (!acc[name]) acc[name] = { name, label: d.label, count: 0 };
      acc[name].count += 1;
      return acc;
    }, {})
  ).sort((a, b) => b.count - a.count);

  return (
    <div className="grid grid-cols-3 gap-6">
      <div className="col-span-2 space-y-6">

        {emergencyActive && (
          <div className="flex items-center gap-3 bg-orange-950/60 border border-orange-500/50 rounded-lg px-4 py-3 shadow-lg animate-pulse">
            <Flame size={20} className="text-orange-400" />
            <div>
              <p className="text-sm font-bold text-orange-300 tracking-wide">EMERGENCY — FIRE/SMOKE DETECTED</p>
              <p className="text-[11px] text-orange-400/80 font-mono">Feed {activeStream.toUpperCase()} · safety division auto-notified</p>
            </div>
          </div>
        )}

        <div className="flex items-center gap-4 bg-slate-900/50 p-2 rounded-lg border border-slate-800/50 w-fit">
          <label htmlFor="camera-select" className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Select Feed:
          </label>
          <div className="relative">
            <select
              id="camera-select"
              value={activeStream}
              onChange={(e) => setActiveStream(e.target.value)}
              className="appearance-none bg-slate-950 border border-slate-700 text-slate-200 text-sm font-semibold rounded-md focus:ring-blue-500 focus:border-blue-500 block w-64 p-2 pl-9 cursor-pointer hover:border-slate-500 transition-colors"
            >
              {CAMERA_REGISTRY.map((cam) => (
                <option key={cam.id} value={cam.id}>{cam.label}</option>
              ))}
            </select>
            <Video size={16} className="absolute left-2.5 top-2.5 text-blue-500 pointer-events-none" />
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 shadow-2xl relative">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-sm font-semibold flex items-center gap-2 text-slate-200">
              <Camera size={18} className="text-blue-400" /> Active Feed // {activeStream.toUpperCase()}
            </h2>
            <button
              onClick={togglePause}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${
                paused
                  ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30'
                  : 'bg-slate-950 border-slate-700 text-slate-300 hover:border-slate-500'
              }`}
            >
              {paused ? <><Play size={13} /> Resume Feed</> : <><Pause size={13} /> Pause Feed</>}
            </button>
          </div>

          <div className="bg-slate-950 h-[480px] rounded-lg border border-slate-800 flex items-center justify-center relative overflow-hidden shadow-inner">
            <img
              key={activeStream}
              src={`${API_BASE}/api/video/${activeStream}`}
              alt="CCTV Stream"
              className="w-full h-full object-contain"
            />
            {paused && (
              <div className="absolute top-3 left-3 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-950/80 border border-slate-700 text-slate-300 text-xs font-mono">
                <Pause size={12} /> PAUSED
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Pending Review</p>
            <p className="text-3xl font-mono font-bold mt-1 text-amber-400">{pendingIncidents.length}</p>
          </div>
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Active Violations</p>
            <p className="text-3xl font-mono font-bold mt-1 text-red-400">{violationCount}</p>
          </div>
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Safety Status</p>
            <p className={`text-xl font-mono font-bold mt-2 ${
              emergencyActive ? 'text-orange-400 animate-pulse'
              : violationCount > 0 ? 'text-red-500 animate-pulse'
              : 'text-emerald-400'
            }`}>
              {emergencyActive ? 'EMERGENCY' : violationCount > 0 ? 'VIOLATION' : 'SECURE'}
            </p>
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <h2 className="text-sm font-semibold flex items-center gap-2 mb-3 text-slate-200">
            <ScanLine size={16} className="text-blue-400" /> Live Detection Breakdown // {activeStream.toUpperCase()}
          </h2>
          {breakdown.length === 0 ? (
            <div className="bg-slate-950 p-5 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">
              No objects currently detected on this feed.
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {breakdown.map((d) => (
                <span
                  key={d.name}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-md border text-xs font-semibold ${labelTone(d.label)}`}
                >
                  {d.name}
                  <span className="font-mono bg-slate-950/60 px-1.5 rounded text-[11px]">{d.count}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="col-span-1 space-y-6">
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-sm font-semibold flex items-center gap-2 text-amber-400"><AlertTriangle size={16} /> Incident Verification Queue</h2>
            <span className="text-xs bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded-full font-mono font-bold">{pendingIncidents.length} New</span>
          </div>
          <div className="space-y-3 max-h-[320px] overflow-y-auto pr-1">
            {pendingIncidents.length === 0 ? (
              <div className="bg-slate-950 p-6 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">No pending incidents requiring review.</div>
            ) : (
              pendingIncidents.map((incident) => {
                const isEmergency = incident.eventType === 'EMERGENCY';
                return (
                  <div key={incident.id} className={`bg-slate-950 border p-3.5 rounded-lg space-y-2.5 ${isEmergency ? 'border-orange-500/40' : 'border-amber-500/30'}`}>
                    <div className="flex justify-between items-center text-xs">
                      <span className="font-mono text-slate-400">{incident.time}</span>
                      <span className={`font-bold px-2 py-0.5 rounded border flex items-center gap-1 ${
                        isEmergency ? 'text-orange-300 bg-orange-950/50 border-orange-800/40' : 'text-red-400 bg-red-950/50 border-red-800/40'
                      }`}>
                        {isEmergency && <Flame size={11} />}{incident.type}
                      </span>
                    </div>
                    <div className="flex justify-between items-center pt-1">
                      <span className="text-[11px] text-slate-300 flex items-center gap-1"><MapPin size={12} /> {incident.zone}</span>
                      <div className="flex gap-2">
                        <button onClick={() => handleVerifyIncident(incident.id, 'DISMISSED')} className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs flex items-center gap-1"><XCircle size={14} /> Dismiss</button>
                        <button onClick={() => handleVerifyIncident(incident.id, 'CONFIRMED')} className="px-2.5 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-xs flex items-center gap-1 font-semibold"><CheckCircle size={14} /> Confirm</button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <h2 className="text-sm font-semibold flex items-center gap-2 mb-3 text-blue-400"><Bot size={16} /> AI Agent Activity</h2>
          <div className="space-y-2.5 max-h-[200px] overflow-y-auto pr-1">
            {notifications.length === 0 ? (
              <div className="bg-slate-950 p-5 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">Agent idle — no notifications dispatched.</div>
            ) : (
              notifications.map((n) => (
                <div key={n.id} className={`bg-slate-950 border p-3 rounded-lg text-xs ${n.severity === 'critical' ? 'border-orange-500/40' : 'border-slate-800'}`}>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <div className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${n.severity === 'critical' ? 'bg-orange-400' : 'bg-amber-400'}`}></span>
                      <span className="font-mono text-[10px] text-slate-500">{n.timestamp}</span>
                    </div>
                    <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${
                      n.dispatched
                        ? 'text-emerald-400 border-emerald-800/50 bg-emerald-950/30'
                        : 'text-slate-500 border-slate-800 bg-slate-900'
                    }`}>
                      {n.dispatched ? 'SENT · TELEGRAM' : 'LOCAL ONLY'}
                    </span>
                  </div>
                  <p className="text-slate-300 leading-snug">{n.message}</p>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <h2 className="text-sm font-semibold flex items-center gap-2 mb-3 text-red-400"><ShieldAlert size={16} /> Confirmed Incident Registry</h2>
          <div className="space-y-2.5 max-h-[220px] overflow-y-auto pr-1">
            {verifiedIncidents.length === 0 ? (
              <div className="bg-slate-950 p-5 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">No confirmed incidents yet.</div>
            ) : (
              verifiedIncidents.map((log, index) => (
                <div key={index} className="bg-slate-950 border border-slate-800 p-3 rounded-lg flex justify-between items-center text-xs">
                  <div><span className="font-bold text-red-400 block">{log.type}</span><span className="text-slate-500 font-mono text-[10px]">{log.time}</span></div>
                  <span className="text-slate-300 bg-slate-900 px-2 py-1 rounded border border-slate-800 text-[11px]">{log.zone}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
