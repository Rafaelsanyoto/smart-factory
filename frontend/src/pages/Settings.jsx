import { useState, useEffect } from 'react';
import {
  Sliders, Camera, Database, Save, Server, Shield, Cpu, Video, Info, WifiOff, Pause, Play,
  Flame, Eye, EyeOff, ScanLine, Bot, ShieldCheck, Zap, ShieldAlert,
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
    description: 'Aksi aman (kirim pesan, toggle tampilan) langsung jalan. Aksi yang mempengaruhi deteksi (zona, confidence, pause, model) tetap minta konfirmasi.',
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

const API_BASE = 'http://127.0.0.1:8000';

export default function Configuration() {
  const [models, setModels] = useState([]);
  const [activeModel, setActiveModel] = useState('');
  const [confidence, setConfidence] = useState(0.65);

  const [allPpe, setAllPpe] = useState([]);
  const [allEmergency, setAllEmergency] = useState([]);
  const [zones, setZones] = useState([]);
  const [sources, setSources] = useState({ options: [], current: {}, paused: {} });

  const [contextClasses, setContextClasses] = useState([]);
  const [contextVisible, setContextVisible] = useState({});

  const [permissionMode, setPermissionMode] = useState('standard');
  const [permissionOptions, setPermissionOptions] = useState(['standard', 'accept_low_risk', 'auto']);

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
        const [mRes, zRes, sRes, cRes, pRes, dRes] = await Promise.all([
          fetch(`${API_BASE}/api/models`),
          fetch(`${API_BASE}/api/zones`),
          fetch(`${API_BASE}/api/sources`),
          fetch(`${API_BASE}/api/context-classes`),
          fetch(`${API_BASE}/api/agent/permission-mode`),
          fetch(`${API_BASE}/api/system/db-info`),
        ]);
        const m = await mRes.json();
        const z = await zRes.json();
        const s = await sRes.json();
        const c = await cRes.json();
        const p = await pRes.json();
        const d = await dRes.json();
        setModels(m.models || []);
        setActiveModel(m.active || '');
        if (typeof m.confidence === 'number') setConfidence(m.confidence);
        setAllPpe(z.all_ppe || []);
        setAllEmergency(z.all_emergency || []);
        setZones(z.zones || []);
        setSources({ options: s.options || [], current: s.current || {}, paused: s.paused || {} });
        setContextClasses(c.classes || []);
        setContextVisible(c.visible || {});
        setPermissionMode(p.mode || 'standard');
        setPermissionOptions(p.options || ['standard', 'accept_low_risk', 'auto']);
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

  const toggleRequired = async (streamId, ppe) => {
    const zone = zones.find((z) => z.stream_id === streamId);
    if (!zone) return;
    const next = zone.required.includes(ppe)
      ? zone.required.filter((p) => p !== ppe)
      : [...zone.required, ppe];
    setZones((prev) => prev.map((z) => (z.stream_id === streamId ? { ...z, required: next } : z)));
    try {
      await fetch(`${API_BASE}/api/zones/${streamId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ required: next }),
      });
      flash(setSaveStatus, `Rules updated for ${zone.label}.`);
    } catch {
      flash(setSaveStatus, 'Rule update failed — backend offline.');
    }
  };

  const toggleEmergency = async (streamId, cls) => {
    const zone = zones.find((z) => z.stream_id === streamId);
    if (!zone) return;
    const current = zone.emergency || [];
    const next = current.includes(cls) ? current.filter((c) => c !== cls) : [...current, cls];
    setZones((prev) => prev.map((z) => (z.stream_id === streamId ? { ...z, emergency: next } : z)));
    try {
      await fetch(`${API_BASE}/api/zones/${streamId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emergency: next }),
      });
      flash(setSaveStatus, `Emergency detection updated for ${zone.label}.`);
    } catch {
      flash(setSaveStatus, 'Emergency rule update failed — backend offline.');
    }
  };

  const toggleContextVisibility = async (cls) => {
    const next = !contextVisible[cls];
    setContextVisible((prev) => ({ ...prev, [cls]: next }));
    try {
      await fetch(`${API_BASE}/api/context-classes/${encodeURIComponent(cls)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ visible: next }),
      });
      flash(setSaveStatus, `${cls} display ${next ? 'enabled' : 'hidden'}.`);
    } catch {
      setContextVisible((prev) => ({ ...prev, [cls]: !next }));
      flash(setSaveStatus, 'Display toggle failed — backend offline.');
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
          <p className="text-xs text-slate-400 mt-1">Manage edge node parameters, detection model, and zone compliance rules.</p>
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
            <p className="text-[11px] text-slate-500 mt-2">Higher thresholds reduce false positives but may miss partial violations. Applied on Sync.</p>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <Camera size={16} className="text-amber-400" /> Edge Stream Registry & Zone Rules
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

                  <div>
                    <label className="text-[10px] font-semibold text-slate-500 uppercase block mb-1.5">Required PPE (violation triggers)</label>
                    <div className="flex flex-wrap gap-1.5">
                      {allPpe.map((ppe) => {
                        const on = zone.required.includes(ppe);
                        return (
                          <button
                            key={ppe}
                            onClick={() => toggleRequired(zone.stream_id, ppe)}
                            disabled={offline}
                            className={`px-2.5 py-1 rounded text-[11px] font-semibold border transition-colors disabled:opacity-50 ${
                              on
                                ? 'bg-blue-600/20 border-blue-500/40 text-blue-300'
                                : 'bg-slate-900 border-slate-700 text-slate-500 hover:text-slate-300'
                            }`}
                          >
                            {ppe}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div>
                    <label className="text-[10px] font-semibold text-slate-500 uppercase flex items-center gap-1 mb-1.5">
                      <Flame size={11} className="text-orange-400" /> Emergency Detection
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {allEmergency.map((cls) => {
                        const on = (zone.emergency || []).includes(cls);
                        return (
                          <button
                            key={cls}
                            onClick={() => toggleEmergency(zone.stream_id, cls)}
                            disabled={offline}
                            className={`px-2.5 py-1 rounded text-[11px] font-semibold border transition-colors disabled:opacity-50 ${
                              on
                                ? 'bg-orange-600/20 border-orange-500/40 text-orange-300'
                                : 'bg-slate-900 border-slate-700 text-slate-500 hover:text-slate-300'
                            }`}
                          >
                            {cls}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <p className="text-[10px] text-slate-500 mt-3 flex items-center gap-1">
              <Info size={11} /> One physical webcam can only feed one stream at a time.
            </p>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <ScanLine size={16} className="text-blue-400" /> Detection Display Filter
            </h2>
            <p className="text-[11px] text-slate-500 mb-3">
              These classes never count as a violation — they're context only. Hide them to reduce noise in the video overlay and breakdown panel.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {contextClasses.map((cls) => {
                const on = !!contextVisible[cls];
                return (
                  <button
                    key={cls}
                    onClick={() => toggleContextVisibility(cls)}
                    disabled={offline}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-semibold border transition-colors disabled:opacity-50 ${
                      on
                        ? 'bg-slate-800 border-slate-600 text-slate-200'
                        : 'bg-slate-950 border-slate-800 text-slate-600'
                    }`}
                  >
                    {on ? <Eye size={11} /> : <EyeOff size={11} />} {cls}
                  </button>
                );
              })}
            </div>
          </div>

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

      </div>
    </div>
  );
}
