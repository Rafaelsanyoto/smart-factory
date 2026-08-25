import { useState, useEffect, useRef } from 'react';
import {
  UploadCloud, ScanLine, ShieldAlert, CheckCircle, XCircle, MapPin, AlertTriangle,
  Video, Flame, Bot, Loader2, Send, Trash2, Hash, ImageOff, FileVideo, FileImage,
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

export default function Detect({ pendingIncidents = [], verifiedIncidents = [], refreshIncidents }) {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const fileInputRef = useRef(null);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/notifications`);
        const data = await res.json();
        if (data.status === 'success') setNotifications(data.notifications || []);
      } catch (err) {
        console.error('Notification polling error:', err);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const pickFile = (f) => {
    if (!f) return;
    setFile(f);
    setResult(null);
    setError('');
    setPreviewUrl(URL.createObjectURL(f));
  };

  const runDetection = async () => {
    if (!file || busy) return;
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API_BASE}/api/detect`, { method: 'POST', body: form });
      const data = await res.json();
      if (data.status !== 'success') {
        setError(data.message || 'Gagal memproses file.');
      } else {
        setResult(data);
      }
    } catch {
      setError('Gagal terhubung ke backend.');
    } finally {
      setBusy(false);
      if (typeof refreshIncidents === 'function') refreshIncidents();
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

  const sortedPending = [...pendingIncidents].sort(byUrgencyThenOldest);
  const sortedAwaitingAction = [...verifiedIncidents].filter((i) => !i.actionTaken).sort(byUrgencyThenOldest);
  const sortedActioned = [...verifiedIncidents].filter((i) => i.actionTaken).sort((a, b) => (b.tsMs || 0) - (a.tsMs || 0));
  const sortedVerified = [...sortedAwaitingAction, ...sortedActioned];
  const pendingUrgencyCounts = pendingIncidents.reduce((acc, i) => {
    const key = i.urgency || 'info';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  const detections = result?.detections || [];
  const violationCount = detections.filter((d) => (d.class_name || '').includes('NO-')).length;
  const emergencyActive = detections.some((d) => EMERGENCY_LABELS.includes((d.class_name || '').toUpperCase()));
  const breakdown = Object.values(
    detections.reduce((acc, d) => {
      const name = d.class_name;
      if (!acc[name]) acc[name] = { name, count: 0 };
      acc[name].count += 1;
      return acc;
    }, {})
  ).sort((a, b) => b.count - a.count);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <ScanLine size={20} className="text-blue-400" /> Deteksi
        </h1>
        <p className="text-xs text-slate-400 mt-1">Unggah satu gambar atau video, lalu jalankan satu proses deteksi.</p>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-6">

          <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold flex items-center gap-2 text-slate-200">
                <UploadCloud size={18} className="text-blue-400" /> Unggah Gambar / Video
              </h2>
              {file && <span className="text-[11px] text-slate-500 font-mono flex items-center gap-1">
                {file.type.startsWith('video') ? <FileVideo size={12} /> : <FileImage size={12} />} {file.name}
              </span>}
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,video/*"
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0])}
            />

            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); pickFile(e.dataTransfer.files?.[0]); }}
              className="bg-slate-950 min-h-[300px] rounded-lg border border-dashed border-slate-700 hover:border-blue-500/60 flex items-center justify-center relative overflow-hidden cursor-pointer transition-colors"
            >
              {result?.annotated_image ? (
                <img src={`data:image/jpeg;base64,${result.annotated_image}`} alt="Hasil deteksi" className="w-full h-full object-contain" />
              ) : previewUrl ? (
                file?.type.startsWith('video') ? (
                  <video src={previewUrl} className="w-full h-full object-contain" muted />
                ) : (
                  <img src={previewUrl} alt="Pratinjau" className="w-full h-full object-contain" />
                )
              ) : (
                <div className="text-center text-slate-500 space-y-2">
                  <ImageOff size={28} className="mx-auto text-slate-700" />
                  <p className="text-sm">Klik atau seret gambar/video ke sini</p>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between mt-4">
              <p className="text-[10px] text-slate-500">
                {result ? `${result.frames_processed} frame diproses · ${detections.length} objek terdeteksi` : 'Belum ada hasil.'}
              </p>
              <button
                onClick={runDetection}
                disabled={!file || busy}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-semibold px-4 py-2 rounded-md text-sm transition-colors"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : <ScanLine size={15} />}
                {busy ? 'Memproses…' : 'Mulai Proses'}
              </button>
            </div>
            {error && <p className="text-[11px] text-red-400 mt-2">{error}</p>}
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
              <p className="text-xs text-slate-400 uppercase">Menunggu Review</p>
              <p className="text-3xl font-mono font-bold mt-1 text-amber-400">{pendingIncidents.length}</p>
            </div>
            <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
              <p className="text-xs text-slate-400 uppercase">Pelanggaran (hasil ini)</p>
              <p className="text-3xl font-mono font-bold mt-1 text-red-400">{violationCount}</p>
            </div>
            <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
              <p className="text-xs text-slate-400 uppercase">Status Hasil</p>
              <p className={`text-xl font-mono font-bold mt-2 ${
                emergencyActive ? 'text-orange-400 animate-pulse'
                : violationCount > 0 ? 'text-red-500'
                : 'text-emerald-400'
              }`}>
                {!result ? '—' : emergencyActive ? 'DARURAT' : violationCount > 0 ? 'PELANGGARAN' : 'AMAN'}
              </p>
            </div>
          </div>

          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
            <h2 className="text-sm font-semibold flex items-center gap-2 mb-1 text-slate-200">
              <Video size={16} className="text-blue-400" /> Rincian Deteksi
            </h2>
            <p className="text-[10px] text-slate-500 mb-3">Hasil objek yang terdeteksi pada proses terakhir.</p>
            {breakdown.length === 0 ? (
              <div className="bg-slate-950 p-5 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">
                Belum ada hasil deteksi. Unggah file lalu klik "Mulai Proses".
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {breakdown.map((d) => (
                  <span
                    key={d.name}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-md border text-xs font-semibold ${labelTone(d.name.toUpperCase())}`}
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
          </div>

          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
            <h2 className="text-sm font-semibold flex items-center gap-2 mb-3 text-blue-400"><Bot size={16} /> Aktivitas AI Agent</h2>
            <div className="space-y-2.5 max-h-[200px] overflow-y-auto pr-1">
              {notifications.length === 0 ? (
                <div className="bg-slate-950 p-5 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">Belum ada notifikasi dikirim.</div>
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
                        <span className="font-bold text-red-400">{log.type}</span>
                        <span className="text-slate-500 font-mono text-[10px] flex items-center gap-1"><Hash size={9} />{log.seq ?? '?'} · {log.time}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
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
                          <CheckCircle size={11} /> Sudah ditindak · {log.actionAt}
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
          </div>
        </div>
      </div>
    </div>
  );
}
