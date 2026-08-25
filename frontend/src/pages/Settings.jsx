import { useState, useEffect } from 'react';
import {
  Sliders, Camera, Database, Save, Server, Shield, Cpu, Video, Info, WifiOff, Pause, Play,
  Eye, EyeOff, Crosshair, Bot, ShieldCheck, Zap, ShieldAlert, Radar,
} from 'lucide-react';

// Full static Tailwind class strings (not interpolated) so the JIT scanner picks them up.
const PERMISSION_MODE_META = {
  standard: {
    label: 'Standard',
    icon: ShieldCheck,
    description: 'Semua aksi (aman maupun berisiko) selalu minta konfirmasi kamu dulu.',
    activeClass: 'bg-emerald-600/20 border-emerald-500/40 text-emerald-300',
    iconClass: 'text-emerald-400',
  },
  accept_low_risk: {
    label: 'Accept Low-Risk',
    icon: Zap,
    description: 'Aksi aman (kirim pesan, catat tindakan) langsung jalan. Aksi yang mempengaruhi deteksi (kelas zona, confidence, source, model) tetap minta konfirmasi.',
    activeClass: 'bg-amber-600/20 border-amber-500/40 text-amber-300',
    iconClass: 'text-amber-400',
  },
  auto: {
    label: 'Full Auto',
    icon: ShieldAlert,
    description: 'Semua aksi langsung jalan tanpa konfirmasi — termasuk yang mempengaruhi deteksi. Pakai dengan hati-hati.',
    activeClass: 'bg-red-600/20 border-red-500/40 text-red-300',
    iconClass: 'text-red-400',
  },
};

// Urgency tier -> static Tailwind classes for the per-class dropdown accent.
const URGENCY_CLASS = {
  info: 'text-slate-400 border-slate-700',
  warning: 'text-amber-300 border-amber-600/50',
  critical: 'text-red-300 border-red-600/50',
};

const API_BASE = 'http://127.0.0.1:8000';

export default function Configuration() {
  const [models, setModels] = useState([]);
  const [activeModel, setActiveModel] = useState('');
  const [confidence, setConfidence] = useState(0.65);

  const [allClasses, setAllClasses] = useState([]);
  const [urgencyLevels, setUrgencyLevels] = useState(['info', 'warning', 'critical']);
  const [zones, setZones] = useState([]);
  const [sources, setSources] = useState({ options: [], current: {}, paused: {} });

  const [permissionMode, setPermissionMode] = useState('standard');
  const [permissionOptions, setPermissionOptions] = useState(['standard', 'accept_low_risk', 'auto']);
  const [autonomousMode, setAutonomousMode] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const [offline, setOffline] = useState(false);
  const [saveStatus, setSaveStatus] = useState('');
  const [modelStatus, setModelStatus] = useState('');

  const [dbInfo, setDbInfo] = useState(null);

  const flash = (setter, msg, ms = 3000) => {
    setter(msg);
    if (ms) setTimeout(() => setter(''), ms);
  };

  // Load current backend configuration
  useEffect(() => {
    (async () => {
      try {
        const [mRes, zRes, sRes, pRes, aRes, dRes, fRes] = await Promise.all([
          fetch(`${API_BASE}/api/models`),
          fetch(`${API_BASE}/api/zones`),
          fetch(`${API_BASE}/api/sources`),
          fetch(`${API_BASE}/api/agent/permission-mode`),
          fetch(`${API_BASE}/api/system/autonomous`),
          fetch(`${API_BASE}/api/system/db-info`),
          fetch(`${API_BASE}/api/system/agent-feedback`),
        ]);
        const m = await mRes.json();
        const z = await zRes.json();
        const s = await sRes.json();
        const p = await pRes.json();
        const a = await aRes.json();
        const d = await dRes.json();
        const f = await fRes.json();
        setFeedback(f);
        setModels(m.models || []);
        setActiveModel(m.active || '');
        if (typeof m.confidence === 'number') setConfidence(m.confidence);
        setAllClasses(z.all_classes || []);
        setUrgencyLevels(z.urgency_levels || ['info', 'warning', 'critical']);
        setZones(z.zones || []);
        setSources({ options: s.options || [], current: s.current || {}, paused: s.paused || {} });
        setPermissionMode(p.mode || 'standard');
        setPermissionOptions(p.options || ['standard', 'accept_low_risk', 'auto']);
        setAutonomousMode(!!a.autonomous_mode);
        setDbInfo(d);
        setOffline(false);
      } catch {
        setOffline(true);
      }
    })();
  }, []);

  const handleModelChange = async (id) => {
    const prev = activeModel;
    setActiveModel(id);
    const label = models.find((m) => m.id === id)?.label || id;
    setModelStatus(`Switching to ${label}… reloading weights on edge node.`);
    try {
      const res = await fetch(`${API_BASE}/api/model/select`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      });
      const data = await res.json();
      if (data.status === 'success') flash(setModelStatus, `Model active: ${label}.`);
      else { setActiveModel(prev); flash(setModelStatus, 'Model switch failed.'); }
    } catch {
      setActiveModel(prev);
      flash(setModelStatus, 'Model switch failed — backend offline.');
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaveStatus('Syncing thresholds to edge node…');
    try {
      await fetch(`${API_BASE}/api/config/confidence`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confidence }),
      });
      flash(setSaveStatus, 'Configuration synced successfully.', 4000);
    } catch {
      flash(setSaveStatus, 'Sync failed — backend offline.', 4000);
    }
  };

  // Merge a partial change into one class of one zone (display/monitor/urgency), optimistic
  // with rollback on failure.
  const updateZoneClass = async (streamId, className, patch) => {
    const zone = zones.find((z) => z.stream_id === streamId);
    const before = zone?.classes?.[className];
    setZones((prev) => prev.map((z) =>
      z.stream_id === streamId
        ? { ...z, classes: { ...z.classes, [className]: { ...z.classes[className], ...patch } } }
        : z,
    ));
    try {
      await fetch(`${API_BASE}/api/zones/${streamId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ classes: { [className]: patch } }),
      });
      flash(setSaveStatus, `${className} diperbarui di ${zone?.label || streamId}.`);
    } catch {
      setZones((prev) => prev.map((z) =>
        z.stream_id === streamId ? { ...z, classes: { ...z.classes, [className]: before } } : z));
      flash(setSaveStatus, 'Update gagal — backend offline.');
    }
  };

  const togglePause = async (streamId) => {
    const next = !sources.paused[streamId];
    setSources((prev) => ({ ...prev, paused: { ...prev.paused, [streamId]: next } }));
    try {
      await fetch(`${API_BASE}/api/stream/${streamId}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paused: next }),
      });
      flash(setSaveStatus, `${streamId} ${next ? 'paused' : 'resumed'}.`);
    } catch {
      setSources((prev) => ({ ...prev, paused: { ...prev.paused, [streamId]: !next } }));
      flash(setSaveStatus, 'Pause toggle failed — backend offline.');
    }
  };

  const handlePermissionModeChange = async (mode) => {
    const prev = permissionMode;
    setPermissionMode(mode);
    try {
      const res = await fetch(`${API_BASE}/api/agent/permission-mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      const data = await res.json();
      if (data.status === 'success') flash(setSaveStatus, `Mode izin AI Agent: ${PERMISSION_MODE_META[mode]?.label || mode}.`);
      else { setPermissionMode(prev); flash(setSaveStatus, 'Gagal mengubah mode izin.'); }
    } catch {
      setPermissionMode(prev);
      flash(setSaveStatus, 'Gagal mengubah mode izin — backend offline.');
    }
  };

  const toggleAutonomous = async () => {
    const next = !autonomousMode;
    setAutonomousMode(next);
    try {
      const res = await fetch(`${API_BASE}/api/system/autonomous`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      });
      const data = await res.json();
      if (data.status === 'success') flash(setSaveStatus, `Mode otonom ${next ? 'AKTIF' : 'nonaktif'}.`);
      else { setAutonomousMode(!next); flash(setSaveStatus, 'Gagal mengubah mode otonom.'); }
    } catch {
      setAutonomousMode(!next);
      flash(setSaveStatus, 'Gagal mengubah mode otonom — backend offline.');
    }
  };

  const handleSourceChange = async (streamId, source) => {
    setSources((prev) => ({ ...prev, current: { ...prev.current, [streamId]: source } }));
    try {
      await fetch(`${API_BASE}/api/stream/${streamId}/source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
      });
      flash(setSaveStatus, `Source updated for ${streamId}.`);
    } catch {
      flash(setSaveStatus, 'Source update failed — backend offline.');
    }
  };

  return (
    <div className="max-w-5xl space-y-6">

      <div className="flex justify-between items-end mb-6">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Sliders size={20} className="text-blue-400" /> System Configuration
          </h1>
          <p className="text-xs text-slate-400 mt-1">Kelola parameter edge node, model deteksi, dan aturan kelas per zona.</p>
        </div>
        <button
          onClick={handleSave}
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-md text-sm font-bold flex items-center gap-2 transition-colors"
        >
          <Save size={16} /> Sync Thresholds
        </button>
      </div>

      {offline && (
        <div className="bg-red-950/50 border border-red-500/50 text-red-400 text-xs font-mono p-3 rounded-lg flex items-center gap-2">
          <WifiOff size={14} /> Backend offline — configuration cannot be loaded or applied. Start api.py.
        </div>
      )}
      {saveStatus && (
        <div className="bg-emerald-950/50 border border-emerald-500/50 text-emerald-400 text-xs font-mono p-3 rounded-lg flex items-center gap-2">
          <Server size={14} /> {saveStatus}
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">

        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl space-y-6">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3">
              <Shield size={16} className="text-emerald-400" /> Vision Model Parameters
            </h2>

            <div>
              <label className="text-xs font-semibold text-slate-400 uppercase flex items-center gap-1.5 mb-2">
                <Cpu size={13} className="text-blue-400" /> Detection Model
              </label>
              <select
                value={activeModel}
                onChange={(e) => handleModelChange(e.target.value)}
                disabled={offline}
                className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-sm font-semibold rounded-md focus:ring-blue-500 focus:border-blue-500 p-2.5 cursor-pointer disabled:opacity-50"
              >
                {models.length === 0 && <option>—</option>}
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
              {modelStatus && <p className="text-[11px] text-blue-400 mt-2 font-mono">{modelStatus}</p>}
            </div>

            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="text-xs font-semibold text-slate-400 uppercase">Detection Confidence Threshold</label>
                <span className="text-xs bg-slate-950 px-2 py-1 rounded border border-slate-700 font-mono text-blue-400">
                  {(confidence * 100).toFixed(0)}%
                </span>
              </div>
              <input
                type="range"
                min="0.1"
                max="0.95"
                step="0.05"
                value={confidence}
                onChange={(e) => setConfidence(parseFloat(e.target.value))}
                disabled={offline}
                className="w-full accent-blue-500 disabled:opacity-50"
              />
              <p className="text-[11px] text-slate-500 mt-2">Threshold lebih tinggi mengurangi false positive tapi bisa melewatkan pelanggaran parsial. Diterapkan saat Sync.</p>
            </div>
          </div>

          {/* Autonomous Incident Handling */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <Radar size={16} className="text-purple-400" /> Penanganan Insiden Otonom
            </h2>
            <button
              onClick={toggleAutonomous}
              disabled={offline}
              className={`w-full text-left flex items-start gap-3 px-3.5 py-3 rounded-lg border transition-colors disabled:opacity-50 ${
                autonomousMode
                  ? 'bg-purple-600/20 border-purple-500/40 text-purple-200'
                  : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
              }`}
            >
              <div className={`mt-0.5 w-9 h-5 rounded-full shrink-0 relative transition-colors ${autonomousMode ? 'bg-purple-500' : 'bg-slate-700'}`}>
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${autonomousMode ? 'left-[18px]' : 'left-0.5'}`} />
              </div>
              <div>
                <p className="text-xs font-semibold">{autonomousMode ? 'AKTIF — AI menangani insiden otomatis' : 'Nonaktif — semua insiden ditinjau manusia'}</p>
                <p className="text-[10px] opacity-80 mt-1 leading-snug">
                  Saat aktif, setiap deteksi baru diverifikasi AI secara visual, lalu di-CONFIRM & dieskalasi otomatis. AI tidak pernah menghapus/menolak sendiri — yang meragukan tetap diserahkan ke kamu.
                </p>
              </div>
            </button>
            {feedback && feedback.agent_confirmed > 0 && (
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-2">
                  <p className="text-[9px] text-slate-500 uppercase">Akurasi AI</p>
                  <p className="font-mono font-bold text-sm text-purple-300">{feedback.accuracy != null ? `${Math.round(feedback.accuracy * 100)}%` : '—'}</p>
                </div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-2">
                  <p className="text-[9px] text-slate-500 uppercase">Di-CONFIRM AI</p>
                  <p className="font-mono font-bold text-sm text-slate-200">{feedback.agent_confirmed}</p>
                </div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-2">
                  <p className="text-[9px] text-slate-500 uppercase">Koreksi</p>
                  <p className="font-mono font-bold text-sm text-amber-300">{feedback.mistakes}</p>
                </div>
              </div>
            )}
            <p className="text-[10px] text-slate-500 mt-3 flex items-center gap-1">
              <Info size={11} /> Butuh GEMINI_API_KEY + GEMINI_VISION_MODEL di .env untuk verifikasi visual. Reminder: critical tiap 2 mnt, warning tiap 10 mnt sampai ditindak.
            </p>
          </div>

          {/* AI Agent permission mode */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <Bot size={16} className="text-blue-400" /> AI Agent Permission Mode
            </h2>
            <div className="space-y-2">
              {permissionOptions.map((mode) => {
                const meta = PERMISSION_MODE_META[mode] || { label: mode, icon: Bot, description: '', activeClass: '', iconClass: '' };
                const Icon = meta.icon;
                const active = permissionMode === mode;
                return (
                  <button
                    key={mode}
                    onClick={() => handlePermissionModeChange(mode)}
                    disabled={offline}
                    className={`w-full text-left flex items-start gap-2.5 px-3 py-2.5 rounded-lg border transition-colors disabled:opacity-50 ${
                      active ? meta.activeClass : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                    }`}
                  >
                    <Icon size={15} className={`mt-0.5 shrink-0 ${active ? '' : meta.iconClass}`} />
                    <div>
                      <p className="text-xs font-semibold">{meta.label}</p>
                      <p className="text-[10px] opacity-80 mt-0.5 leading-snug">{meta.description}</p>
                    </div>
                  </button>
                );
              })}
            </div>
            <p className="text-[10px] text-slate-500 mt-3 flex items-center gap-1">
              <Info size={11} /> Ini juga berlaku untuk chat lewat Discord — satu mode, semua channel.
            </p>
          </div>

          {/* SQLite */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <Database size={16} className="text-purple-400" /> Local Persistence (SQLite)
            </h2>
            {dbInfo ? (
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3">
                  <p className="text-slate-500 uppercase text-[10px] mb-1">Insiden Tercatat</p>
                  <p className="font-mono font-bold text-slate-200 text-lg">{dbInfo.event_count}</p>
                </div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3">
                  <p className="text-slate-500 uppercase text-[10px] mb-1">Notifikasi Tercatat</p>
                  <p className="font-mono font-bold text-slate-200 text-lg">{dbInfo.notification_count}</p>
                </div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 col-span-2">
                  <p className="text-slate-500 uppercase text-[10px] mb-1">Ukuran File</p>
                  <p className="font-mono text-slate-300">{dbInfo.size_kb} KB</p>
                  <p className="font-mono text-slate-600 text-[10px] mt-1 break-all">{dbInfo.path}</p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500">Memuat info database…</p>
            )}
            <p className="text-[10px] text-slate-500 mt-3 flex items-center gap-1">
              <Info size={11} /> Semua siklus insiden (deteksi → konfirmasi → tindakan/hapus) tersimpan permanen di sini — bertahan lewat restart server.
            </p>
          </div>
        </div>

        {/* Right column: per-zone streams + class matrix */}
        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <Camera size={16} className="text-amber-400" /> Zona, Sumber & Aturan Kelas
            </h2>

            <div className="space-y-4">
              {zones.length === 0 && (
                <p className="text-xs text-slate-500">No streams available.</p>
              )}
              {zones.map((zone) => (
                <div key={zone.stream_id} className="bg-slate-950 p-3.5 rounded-lg border border-slate-800 space-y-3">
                  <div className="flex justify-between items-start gap-2">
                    <div>
                      <p className="text-xs font-bold text-slate-200">{zone.label}</p>
                      <p className="text-[10px] font-mono text-slate-500">{zone.stream_id}</p>
                    </div>
                    <button
                      onClick={() => togglePause(zone.stream_id)}
                      disabled={offline}
                      className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold border transition-colors disabled:opacity-50 ${
                        sources.paused[zone.stream_id]
                          ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-300'
                          : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {sources.paused[zone.stream_id] ? <><Play size={11} /> Resume</> : <><Pause size={11} /> Pause</>}
                    </button>
                  </div>

                  <div>
                    <label className="text-[10px] font-semibold text-slate-500 uppercase flex items-center gap-1 mb-1">
                      <Video size={11} /> Source
                    </label>
                    <select
                      value={sources.current[zone.stream_id] || ''}
                      onChange={(e) => handleSourceChange(zone.stream_id, e.target.value)}
                      disabled={offline}
                      className="w-full bg-slate-900 border border-slate-700 text-slate-200 text-xs rounded-md focus:ring-blue-500 focus:border-blue-500 p-2 cursor-pointer disabled:opacity-50"
                    >
                      {sources.options.map((opt) => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  </div>

                  {/* Per-class matrix: display / monitor / urgency */}
                  <div>
                    <div className="flex items-center gap-2 text-[10px] font-semibold text-slate-500 uppercase mb-1.5 px-1">
                      <span className="flex-1">Kelas</span>
                      <span title="Tampilkan box di video"><Eye size={11} /></span>
                      <span className="w-12 text-center" title="Jadikan pemicu insiden">Monitor</span>
                      <span className="w-20 text-center">Urgensi</span>
                    </div>
                    <div className="divide-y divide-slate-800/70">
                      {Object.entries(zone.classes || {}).map(([cls, cfg]) => (
                        <div key={cls} className="flex items-center gap-2 py-1">
                          <button
                            onClick={() => updateZoneClass(zone.stream_id, cls, { display: !cfg.display })}
                            disabled={offline}
                            title={cfg.display ? 'Tampil di video' : 'Disembunyikan'}
                            className={`shrink-0 disabled:opacity-50 ${cfg.display ? 'text-slate-300' : 'text-slate-600'}`}
                          >
                            {cfg.display ? <Eye size={13} /> : <EyeOff size={13} />}
                          </button>
                          <span className={`flex-1 text-[11px] font-mono ${cfg.monitor ? 'text-slate-200' : 'text-slate-500'}`}>{cls}</span>
                          <button
                            onClick={() => updateZoneClass(zone.stream_id, cls, { monitor: !cfg.monitor })}
                            disabled={offline}
                            title={cfg.monitor ? 'Memicu insiden' : 'Tidak dimonitor'}
                            className={`w-12 flex justify-center shrink-0 disabled:opacity-50 ${cfg.monitor ? 'text-blue-400' : 'text-slate-700 hover:text-slate-500'}`}
                          >
                            <Crosshair size={14} />
                          </button>
                          <select
                            value={cfg.urgency}
                            onChange={(e) => updateZoneClass(zone.stream_id, cls, { urgency: e.target.value })}
                            disabled={offline || !cfg.monitor}
                            className={`w-20 bg-slate-900 border text-[10px] rounded px-1.5 py-1 cursor-pointer disabled:opacity-40 ${URGENCY_CLASS[cfg.urgency] || URGENCY_CLASS.info}`}
                          >
                            {urgencyLevels.map((u) => (
                              <option key={u} value={u}>{u}</option>
                            ))}
                          </select>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <p className="text-[10px] text-slate-500 mt-3 flex items-center gap-1">
              <Info size={11} /> Contoh: aktifkan Monitor pada <span className="font-mono">Person</span> dengan urgensi <span className="font-mono">critical</span> untuk menjadikan zona ini area terlarang.
            </p>
          </div>
        </div>

      </div>
    </div>
  );
}
