import { useState, useEffect } from 'react';
import {
  Sliders, Database, Save, Server, Shield, Cpu, Info, WifiOff,
  Eye, EyeOff, Crosshair,
} from 'lucide-react';

const URGENCY_CLASS = {
  info: 'text-slate-400 border-slate-700',
  warning: 'text-amber-300 border-amber-600/50',
  critical: 'text-red-300 border-red-600/50',
};

const API_BASE = 'http://127.0.0.1:8000';

export default function Configuration() {
  const [modelLabel, setModelLabel] = useState('');
  const [confidence, setConfidence] = useState(0.65);

  const [allClasses, setAllClasses] = useState([]);
  const [urgencyLevels, setUrgencyLevels] = useState(['info', 'warning', 'critical']);
  const [classes, setClasses] = useState({});

  const [offline, setOffline] = useState(false);
  const [saveStatus, setSaveStatus] = useState('');
  const [dbInfo, setDbInfo] = useState(null);

  const flash = (setter, msg, ms = 3000) => {
    setter(msg);
    if (ms) setTimeout(() => setter(''), ms);
  };

  useEffect(() => {
    (async () => {
      try {
        const [mRes, cRes, dRes] = await Promise.all([
          fetch(`${API_BASE}/api/models`),
          fetch(`${API_BASE}/api/class-rules`),
          fetch(`${API_BASE}/api/system/db-info`),
        ]);
        const m = await mRes.json();
        const c = await cRes.json();
        const d = await dRes.json();
        setModelLabel(m.label || m.active || '');
        if (typeof m.confidence === 'number') setConfidence(m.confidence);
        setAllClasses(c.all_classes || []);
        setUrgencyLevels(c.urgency_levels || ['info', 'warning', 'critical']);
        setClasses(c.classes || {});
        setDbInfo(d);
        setOffline(false);
      } catch {
        setOffline(true);
      }
    })();
  }, []);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaveStatus('Menyimpan confidence threshold…');
    try {
      await fetch(`${API_BASE}/api/config/confidence`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confidence }),
      });
      flash(setSaveStatus, 'Pengaturan berhasil disimpan.', 4000);
    } catch {
      flash(setSaveStatus, 'Gagal menyimpan — backend offline.', 4000);
    }
  };

  const updateClass = async (className, patch) => {
    const before = classes[className];
    setClasses((prev) => ({ ...prev, [className]: { ...prev[className], ...patch } }));
    try {
      await fetch(`${API_BASE}/api/class-rules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ classes: { [className]: patch } }),
      });
      flash(setSaveStatus, `${className} diperbarui.`);
    } catch {
      setClasses((prev) => ({ ...prev, [className]: before }));
      flash(setSaveStatus, 'Update gagal — backend offline.');
    }
  };

  return (
    <div className="max-w-3xl space-y-6">

      <div className="flex justify-between items-end mb-6">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Sliders size={20} className="text-blue-400" /> Konfigurasi Sistem
          </h1>
          <p className="text-xs text-slate-400 mt-1">Kelola confidence deteksi dan aturan kelas.</p>
        </div>
        <button
          onClick={handleSave}
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-md text-sm font-bold flex items-center gap-2 transition-colors"
        >
          <Save size={16} /> Simpan Pengaturan
        </button>
      </div>

      {offline && (
        <div className="bg-red-950/50 border border-red-500/50 text-red-400 text-xs font-mono p-3 rounded-lg flex items-center gap-2">
          <WifiOff size={14} /> Backend offline — pengaturan tidak bisa dimuat atau diterapkan. Jalankan api.py.
        </div>
      )}
      {saveStatus && (
        <div className="bg-emerald-950/50 border border-emerald-500/50 text-emerald-400 text-xs font-mono p-3 rounded-lg flex items-center gap-2">
          <Server size={14} /> {saveStatus}
        </div>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl space-y-6">
        <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3">
          <Shield size={16} className="text-emerald-400" /> Parameter Model Deteksi
        </h2>

        <div>
          <label className="text-xs font-semibold text-slate-400 uppercase flex items-center gap-1.5 mb-2">
            <Cpu size={13} className="text-blue-400" /> Model Deteksi
          </label>
          <div className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-sm font-semibold rounded-md p-2.5">
            {modelLabel || '—'}
          </div>
          <p className="text-[11px] text-slate-500 mt-2">Model tunggal untuk MVP ini — tidak bisa diganti dari UI.</p>
        </div>

        <div>
          <div className="flex justify-between items-center mb-2">
            <label className="text-xs font-semibold text-slate-400 uppercase">Confidence Threshold Deteksi</label>
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
          <p className="text-[11px] text-slate-500 mt-2">Threshold lebih tinggi mengurangi false positive tapi bisa melewatkan pelanggaran parsial. Diterapkan saat disimpan.</p>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
        <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
          <Crosshair size={16} className="text-amber-400" /> Aturan Kelas
        </h2>

        <div className="flex items-center gap-2 text-[10px] font-semibold text-slate-500 uppercase mb-1.5 px-1">
          <span className="flex-1">Kelas</span>
          <span title="Tampilkan box di gambar hasil"><Eye size={11} /></span>
          <span className="w-12 text-center" title="Jadikan pemicu insiden">Monitor</span>
          <span className="w-20 text-center">Urgensi</span>
        </div>
        <div className="divide-y divide-slate-800/70">
          {allClasses.length === 0 && (
            <p className="text-xs text-slate-500 py-3">Memuat aturan kelas…</p>
          )}
          {allClasses.map((cls) => {
            const cfg = classes[cls] || { display: true, monitor: false, urgency: 'info' };
            return (
              <div key={cls} className="flex items-center gap-2 py-1.5">
                <button
                  onClick={() => updateClass(cls, { display: !cfg.display })}
                  disabled={offline}
                  title={cfg.display ? 'Tampil di gambar hasil' : 'Disembunyikan'}
                  className={`shrink-0 disabled:opacity-50 ${cfg.display ? 'text-slate-300' : 'text-slate-600'}`}
                >
                  {cfg.display ? <Eye size={13} /> : <EyeOff size={13} />}
                </button>
                <span className={`flex-1 text-[11px] font-mono ${cfg.monitor ? 'text-slate-200' : 'text-slate-500'}`}>{cls}</span>
                <button
                  onClick={() => updateClass(cls, { monitor: !cfg.monitor })}
                  disabled={offline}
                  title={cfg.monitor ? 'Memicu insiden' : 'Tidak dimonitor'}
                  className={`w-12 flex justify-center shrink-0 disabled:opacity-50 ${cfg.monitor ? 'text-blue-400' : 'text-slate-700 hover:text-slate-500'}`}
                >
                  <Crosshair size={14} />
                </button>
                <select
                  value={cfg.urgency}
                  onChange={(e) => updateClass(cls, { urgency: e.target.value })}
                  disabled={offline || !cfg.monitor}
                  className={`w-20 bg-slate-900 border text-[10px] rounded px-1.5 py-1 cursor-pointer disabled:opacity-40 ${URGENCY_CLASS[cfg.urgency] || URGENCY_CLASS.info}`}
                >
                  {urgencyLevels.map((u) => (
                    <option key={u} value={u}>{u}</option>
                  ))}
                </select>
              </div>
            );
          })}
        </div>
        <p className="text-[10px] text-slate-500 mt-3 flex items-center gap-1">
          <Info size={11} /> Insiden dari kelas yang dimonitor selalu berstatus PENDING — menunggu review manusia.
        </p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
        <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
          <Database size={16} className="text-purple-400" /> Penyimpanan Lokal (SQLite)
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
      </div>
    </div>
  );
}
