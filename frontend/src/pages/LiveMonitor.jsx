import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Camera, ShieldAlert, CheckCircle, XCircle, MapPin, AlertTriangle,
  Video, Flame, Bot, ScanLine, Pause, Play, Clock, CheckCheck, Info, Send, Loader2, Trash2, Hash, Radar,
  ArrowRight,
} from 'lucide-react';

const URGENCY_RANK = { critical: 0, warning: 1, info: 2 };
function byUrgencyThenOldest(a, b) {
  const ra = URGENCY_RANK[a.urgency] ?? 3;
  const rb = URGENCY_RANK[b.urgency] ?? 3;
  if (ra !== rb) return ra - rb;
  return (a.tsMs || 0) - (b.tsMs || 0);
}

const API_BASE = 'http://127.0.0.1:8000';

const URGENCY_META = {
  info: { label: 'INFO', cls: 'text-slate-400 bg-slate-800/60 border-slate-700' },
  warning: { label: 'WARNING', cls: 'text-amber-300 bg-amber-950/50 border-amber-800/40' },
  critical: { label: 'CRITICAL', cls: 'text-red-300 bg-red-950/50 border-red-800/40' },
};

const AGENT_VERDICT_META = {
  real: { label: 'AI: pelanggaran nyata', cls: 'text-emerald-300 bg-emerald-950/40 border-emerald-800/40' },
  false: { label: 'AI: kemungkinan salah deteksi', cls: 'text-slate-300 bg-slate-800/60 border-slate-700' },
  uncertain: { label: 'AI: ragu — perlu review', cls: 'text-amber-300 bg-amber-950/40 border-amber-800/40' },
};

const OVERDUE_MS = { critical: 120_000, warning: 600_000 };
function isOverdue(log) {
  if (log.actionTaken || !log.tsMs) return false;
  const limit = OVERDUE_MS[log.urgency];
  return limit ? Date.now() - log.tsMs > limit : false;
}

const CAMERA_REGISTRY = [
  { id: 'stream_01', label: 'Assembly Line A (Cam 01)' },
  { id: 'stream_02', label: 'Welding Bay B (Cam 02)' },
];

const EMERGENCY_LABELS = ['FIRE', 'SMOKE'];

function labelTone(label) {
  if (label.includes('NO-')) return 'text-red-400 border-red-800/40 bg-red-950/40';
  if (EMERGENCY_LABELS.includes(label)) return 'text-orange-400 border-orange-800/40 bg-orange-950/40';
  if (label === 'PERSON') return 'text-slate-300 border-slate-700 bg-slate-800/40';
  return 'text-emerald-400 border-emerald-800/40 bg-emerald-950/30';
}

function ActionForm({ incidentId, onSubmit }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (!note.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      await onSubmit(incidentId, note.trim());
    } catch (err) {
      setError(err.message || 'Gagal mencatat tindakan.');
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="mt-2 pt-2 border-t border-slate-800 space-y-1.5">
      <div className="flex gap-1.5">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={busy}
          placeholder="Catat tindakan yang diambil…"
          className="flex-1 bg-slate-900 border border-slate-700 text-slate-200 text-[11px] rounded-md focus:ring-blue-500 focus:border-blue-500 px-2 py-1.5 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={busy || !note.trim()}
          className="px-2.5 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-md flex items-center gap-1"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
        </button>
      </div>
      {error && <p className="text-[10px] text-red-400">{error}</p>}
    </form>
  );
}

export default function LiveMonitor({ pendingIncidents = [], verifiedIncidents = [], refreshIncidents }) {
  const [activeStream, setActiveStream] = useState('stream_01');
  const [allDetections, setAllDetections] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [emergencyActive, setEmergencyActive] = useState(false);
  const [paused, setPaused] = useState(false);

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

        setEmergencyActive(parsed.some((d) => EMERGENCY_LABELS.includes(d.label)));
      } catch (err) {
        console.error('Data polling error:', err);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [activeStream]);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/notifications`);
        const data = await res.json();
        if (data.status === 'success') setNotifications(data.notifications || []);
      } catch (err) {
        console.error('Notification polling error:', err);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, []);

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

  const handleVerifyIncident = async (id, status) => {
    try {
      await fetch(`${API_BASE}/api/events/${id}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
    } catch (err) {
      console.error('Verify incident error:', err);
    }
    if (typeof refreshIncidents === 'function') refreshIncidents();
  };

  const handleRecordAction = async (id, actionNote) => {
    const res = await fetch(`${API_BASE}/api/events/${id}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action_note: actionNote }),
    });
    const data = await res.json();
    if (typeof refreshIncidents === 'function') refreshIncidents();
    if (data.status !== 'success') throw new Error(data.message || 'Gagal mencatat tindakan');
  };

  const handleDeleteIncident = async (id) => {
    try {
      await fetch(`${API_BASE}/api/events/${id}/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Duplikat' }),
      });
    } catch (err) {
      console.error('Delete incident error:', err);
    }
    if (typeof refreshIncidents === 'function') refreshIncidents();
  };

  // sorted so critical/oldest never gets buried under a growing queue
  const sortedPending = [...pendingIncidents].sort(byUrgencyThenOldest);
  const sortedAwaitingAction = [...verifiedIncidents].filter((i) => !i.actionTaken).sort(byUrgencyThenOldest);
  const sortedActioned = [...verifiedIncidents].filter((i) => i.actionTaken).sort((a, b) => (b.tsMs || 0) - (a.tsMs || 0));
  const sortedVerified = [...sortedAwaitingAction, ...sortedActioned];
  const pendingUrgencyCounts = pendingIncidents.reduce((acc, i) => {
    const key = i.urgency || 'info';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  const violationCount = allDetections.filter((d) => d.label.includes('NO-')).length;
  const breakdown = Object.values(
    allDetections.reduce((acc, d) => {
      const name = d.class_name || d.label;
      if (!acc[name]) acc[name] = { name, label: d.label, count: 0, pending: 0, notified: 0 };
      acc[name].count += 1;
      if (d.episode_status === 'pending') acc[name].pending += 1;
      else if (d.episode_status === 'notified') acc[name].notified += 1;
      return acc;
    }, {})
  ).sort((a, b) => b.count - a.count);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <Video size={20} className="text-blue-400" /> Live Monitor
        </h1>
        <p className="text-xs text-slate-400 mt-1">Pantau feed kamera dan tinjau insiden secara langsung.</p>
      </div>

      <div className="grid grid-cols-3 gap-6">
      <div className="col-span-2 space-y-6">

        <div className="flex items-center gap-4 bg-slate-900/50 p-2 rounded-lg border border-slate-800/50 w-fit">
          <label htmlFor="camera-select" className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Pilih Kamera:
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
              <Camera size={18} className="text-blue-400" /> Feed Aktif // {activeStream.toUpperCase()}
            </h2>
            <button
              onClick={togglePause}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${
                paused
                  ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30'
                  : 'bg-slate-950 border-slate-700 text-slate-300 hover:border-slate-500'
              }`}
            >
              {paused ? <><Play size={13} /> Lanjutkan</> : <><Pause size={13} /> Jeda</>}
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
                <Pause size={12} /> DIJEDA
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Menunggu Review</p>
            <p className="text-3xl font-mono font-bold mt-1 text-amber-400">{pendingIncidents.length}</p>
          </div>
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Pelanggaran Aktif</p>
            <p className="text-3xl font-mono font-bold mt-1 text-red-400">{violationCount}</p>
          </div>
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Status Keselamatan</p>
            <p className={`text-xl font-mono font-bold mt-2 ${
              emergencyActive ? 'text-orange-400 animate-pulse'
              : violationCount > 0 ? 'text-red-500 animate-pulse'
              : 'text-emerald-400'
            }`}>
              {emergencyActive ? 'DARURAT' : violationCount > 0 ? 'PELANGGARAN' : 'AMAN'}
            </p>
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-semibold flex items-center gap-2 text-slate-200">
              <ScanLine size={16} className="text-blue-400" /> Rincian Deteksi Langsung // {activeStream.toUpperCase()}
            </h2>
          </div>
          <p className="text-[10px] text-slate-500 mb-3 flex items-center gap-1">
            <Info size={11} /> <Clock size={10} className="text-amber-300" /> menunggu konfirmasi &nbsp;·&nbsp; <CheckCheck size={10} /> sudah dinotifikasi (tidak akan re-alert selama masih episode yang sama)
          </p>
          {breakdown.length === 0 ? (
            <div className="bg-slate-950 p-5 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">
              Tidak ada objek yang terdeteksi pada feed ini saat ini.
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
                  {(d.pending > 0 || d.notified > 0) && (
                    <span className="flex items-center gap-1.5 pl-1.5 ml-0.5 border-l border-current/20 font-mono text-[10px]">
                      {d.pending > 0 && (
                        <span className="flex items-center gap-0.5 text-amber-300" title="Belum notif — masih dikonfirmasi (min. 5 detik)">
                          <Clock size={10} />{d.pending}
                        </span>
                      )}
                      {d.notified > 0 && (
                        <span className="flex items-center gap-0.5 opacity-70" title="Sudah notif untuk episode ini — deteksi lanjutan di posisi ini di-skip">
                          <CheckCheck size={10} />{d.notified}
                        </span>
                      )}
                    </span>
                  )}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="col-span-1 space-y-6">
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <div className="flex justify-between items-center mb-2">
            <h2 className="text-sm font-semibold flex items-center gap-2 text-amber-400"><AlertTriangle size={16} /> Antrean Verifikasi Insiden</h2>
            <span className="text-xs bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded-full font-mono font-bold">{pendingIncidents.length} Baru</span>
          </div>
          {pendingIncidents.length > 0 && (
            <div className="flex items-center gap-1.5 mb-3 text-[10px] font-mono">
              {pendingUrgencyCounts.critical > 0 && (
                <span className="px-1.5 py-0.5 rounded border text-red-300 bg-red-950/50 border-red-800/40">{pendingUrgencyCounts.critical} critical</span>
              )}
              {pendingUrgencyCounts.warning > 0 && (
                <span className="px-1.5 py-0.5 rounded border text-amber-300 bg-amber-950/50 border-amber-800/40">{pendingUrgencyCounts.warning} warning</span>
              )}
              {pendingUrgencyCounts.info > 0 && (
                <span className="px-1.5 py-0.5 rounded border text-slate-400 bg-slate-800/60 border-slate-700">{pendingUrgencyCounts.info} info</span>
              )}
              <span className="text-slate-600">· diurutkan: kritis & terlama dulu</span>
            </div>
          )}
          <div className="space-y-3 max-h-[320px] overflow-y-auto pr-1">
            {sortedPending.length === 0 ? (
              <div className="bg-slate-950 p-6 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">Tidak ada insiden yang menunggu review.</div>
            ) : (
              sortedPending.map((incident) => {
                const isEmergency = incident.eventType === 'EMERGENCY';
                return (
                  <div key={incident.id} className={`bg-slate-950 border p-3.5 rounded-lg space-y-2.5 ${isEmergency ? 'border-orange-500/40' : 'border-amber-500/30'}`}>
                    <div className="flex justify-between items-center text-xs">
                      <span className="font-mono text-slate-500 flex items-center gap-1"><Hash size={10} />{incident.seq ?? '?'} · {incident.time}</span>
                      <div className="flex items-center gap-1.5">
                        {incident.urgency && URGENCY_META[incident.urgency] && (
                          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${URGENCY_META[incident.urgency].cls}`}>
                            {URGENCY_META[incident.urgency].label}
                          </span>
                        )}
                        <span className={`font-bold px-2 py-0.5 rounded border flex items-center gap-1 ${
                          isEmergency ? 'text-orange-300 bg-orange-950/50 border-orange-800/40' : 'text-red-400 bg-red-950/50 border-red-800/40'
                        }`}>
                          {isEmergency && <Flame size={11} />}{incident.type}
                        </span>
                      </div>
                    </div>
                    {incident.verifiedBy === 'agent' && incident.agentVerdict && AGENT_VERDICT_META[incident.agentVerdict] && (
                      <div className={`text-[10px] px-2 py-1 rounded border flex items-start gap-1.5 ${AGENT_VERDICT_META[incident.agentVerdict].cls}`}>
                        <Radar size={11} className="mt-0.5 shrink-0" />
                        <span><span className="font-semibold">{AGENT_VERDICT_META[incident.agentVerdict].label}.</span> {incident.agentReasoning}</span>
                      </div>
                    )}
                    <div className="flex justify-between items-center pt-1">
                      <span className="text-[11px] text-slate-300 flex items-center gap-1"><MapPin size={12} /> {incident.zone}</span>
                      <div className="flex gap-1.5">
                        <button onClick={() => handleDeleteIncident(incident.id)} title="Hapus (duplikat)" className="px-2 py-1 bg-slate-800 hover:bg-red-950/60 text-slate-500 hover:text-red-400 rounded text-xs flex items-center"><Trash2 size={13} /></button>
                        <button onClick={() => handleVerifyIncident(incident.id, 'DISMISSED')} className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs flex items-center gap-1"><XCircle size={14} /> Tolak</button>
                        <button onClick={() => handleVerifyIncident(incident.id, 'CONFIRMED')} className="px-2.5 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-xs flex items-center gap-1 font-semibold"><CheckCircle size={14} /> Konfirmasi</button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          {pendingIncidents.length > 6 && (
            <Link to="/incidents" className="flex items-center justify-center gap-1.5 mt-3 pt-3 border-t border-slate-800 text-[11px] text-blue-400 hover:text-blue-300 font-semibold">
              Kelola semua di halaman Insiden <ArrowRight size={12} />
            </Link>
          )}
        </div>

        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <h2 className="text-sm font-semibold flex items-center gap-2 mb-3 text-blue-400"><Bot size={16} /> Aktivitas AI Agent</h2>
          <div className="space-y-2.5 max-h-[200px] overflow-y-auto pr-1">
            {notifications.length === 0 ? (
              <div className="bg-slate-950 p-5 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">Agent idle — belum ada notifikasi dikirim.</div>
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
                      {n.dispatched ? `TERKIRIM · ${(n.channel || 'EXTERNAL').toUpperCase()}` : 'LOKAL SAJA'}
                    </span>
                  </div>
                  <p className="text-slate-300 leading-snug">{n.message}</p>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-sm font-semibold flex items-center gap-2 text-red-400"><ShieldAlert size={16} /> Daftar Insiden Terkonfirmasi</h2>
            {sortedAwaitingAction.length > 0 && (
              <span className="text-[10px] text-slate-500 font-mono">{sortedAwaitingAction.length} menunggu tindakan</span>
            )}
          </div>
          <div className="space-y-2.5 max-h-[320px] overflow-y-auto pr-1">
            {sortedVerified.length === 0 ? (
              <div className="bg-slate-950 p-5 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">Belum ada insiden yang terkonfirmasi.</div>
            ) : (
              sortedVerified.map((log) => (
                <div key={log.id} className="bg-slate-950 border border-slate-800 p-3 rounded-lg text-xs">
                  <div className="flex justify-between items-center">
                    <div>
                      <span className="font-bold text-red-400 flex items-center gap-1.5">
                        {log.type}
                        {log.verifiedBy === 'agent' && (
                          <span title="Dikonfirmasi otomatis oleh AI" className="text-[8px] font-bold px-1 py-0.5 rounded border text-purple-300 bg-purple-950/40 border-purple-700/50 flex items-center gap-0.5">
                            <Radar size={8} /> AI
                          </span>
                        )}
                      </span>
                      <span className="text-slate-500 font-mono text-[10px] flex items-center gap-1"><Hash size={9} />{log.seq ?? '?'} · {log.time}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {isOverdue(log) && (
                        <span title="Belum ditindak melewati batas waktu urgensinya" className="text-[9px] font-bold px-1.5 py-0.5 rounded border text-red-300 bg-red-950/50 border-red-700/50 flex items-center gap-0.5 animate-pulse">
                          <Clock size={9} /> OVERDUE
                        </span>
                      )}
                      <span className="text-slate-300 bg-slate-900 px-2 py-1 rounded border border-slate-800 text-[11px]">{log.zone}</span>
                      {!log.actionTaken && (
                        <button onClick={() => handleDeleteIncident(log.id)} title="Hapus (duplikat)" className="p-1.5 bg-slate-900 hover:bg-red-950/60 text-slate-500 hover:text-red-400 rounded border border-slate-800">
                          <Trash2 size={12} />
                        </button>
                      )}
                    </div>
                  </div>

                  {log.actionTaken ? (
                    <div className="mt-2 pt-2 border-t border-slate-800">
                      <span className="text-emerald-400 font-semibold flex items-center gap-1 text-[11px]">
                        <CheckCheck size={11} /> Sudah ditindak · {log.actionAt}
                      </span>
                      <p className="text-slate-300 mt-1 leading-snug">{log.actionNote}</p>
                    </div>
                  ) : (
                    <ActionForm incidentId={log.id} onSubmit={handleRecordAction} />
                  )}
                </div>
              ))
            )}
          </div>
          {verifiedIncidents.length > 6 && (
            <Link to="/incidents" className="flex items-center justify-center gap-1.5 mt-3 pt-3 border-t border-slate-800 text-[11px] text-blue-400 hover:text-blue-300 font-semibold">
              Kelola semua di halaman Insiden <ArrowRight size={12} />
            </Link>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
