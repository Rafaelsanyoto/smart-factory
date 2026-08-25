import { useState, useEffect, useCallback } from 'react';
import {
  ClipboardList, Search, FileDown, Radar, CheckCircle, XCircle, Trash2, Send, Loader2,
  Hash, MapPin, TrendingUp, LayoutGrid, Clock, Wrench, CheckCircle2, Flame,
} from 'lucide-react';

const API_BASE = 'http://127.0.0.1:8000';

const STATUS_META = {
  PENDING: { label: 'Menunggu', cls: 'text-amber-300 bg-amber-950/40 border-amber-800/40' },
  CONFIRMED: { label: 'Terkonfirmasi', cls: 'text-red-300 bg-red-950/40 border-red-800/40' },
  DISMISSED: { label: 'Ditolak', cls: 'text-slate-400 bg-slate-800/40 border-slate-700' },
  DELETED: { label: 'Dihapus', cls: 'text-slate-500 bg-slate-800/30 border-slate-700' },
};

const isOpenIncident = (e) => e.status !== 'DISMISSED' && e.status !== 'DELETED';

// quick-filter chips — the fast way to triage without hunting through a long table
const QUICK_FILTERS = [
  { id: 'ALL', label: 'Semua', icon: LayoutGrid, match: () => true },
  { id: 'PENDING', label: 'Pending', icon: Clock, match: (e) => e.status === 'PENDING' },
  { id: 'AWAITING_ACTION', label: 'Menunggu Tindakan', icon: Wrench, match: (e) => e.status === 'CONFIRMED' && !e.action_taken },
  { id: 'ACTIONED', label: 'Sudah Ditindak', icon: CheckCircle2, match: (e) => e.status === 'CONFIRMED' && !!e.action_taken },
  { id: 'CRITICAL_OPEN', label: 'Kritis Belum Selesai', icon: Flame, match: (e) => e.urgency === 'critical' && !e.action_taken && isOpenIncident(e) },
  { id: 'DISMISSED', label: 'Ditolak', icon: XCircle, match: (e) => e.status === 'DISMISSED' },
  { id: 'DELETED', label: 'Dihapus', icon: Trash2, match: (e) => e.status === 'DELETED' },
];

const URGENCY_META = {
  info: { label: 'Info', cls: 'text-slate-400 bg-slate-800/60 border-slate-700' },
  warning: { label: 'Warning', cls: 'text-amber-300 bg-amber-950/50 border-amber-800/40' },
  critical: { label: 'Critical', cls: 'text-red-300 bg-red-950/50 border-red-800/40' },
};

function ActionCell({ event, onVerify, onAction, onDelete }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  if (event.status === 'PENDING') {
    return (
      <div className="flex gap-1.5">
        <button onClick={() => onDelete(event.id)} title="Hapus (duplikat)" className="p-1.5 bg-slate-800 hover:bg-red-950/60 text-slate-500 hover:text-red-400 rounded"><Trash2 size={13} /></button>
        <button onClick={() => onVerify(event.id, 'DISMISSED')} className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-[11px] flex items-center gap-1"><XCircle size={12} /> Tolak</button>
        <button onClick={() => onVerify(event.id, 'CONFIRMED')} className="px-2 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-[11px] flex items-center gap-1 font-semibold"><CheckCircle size={12} /> Konfirmasi</button>
      </div>
    );
  }

  if (event.status === 'CONFIRMED' && !event.action_taken) {
    return (
      <div className="flex gap-1.5 items-center">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Catat tindakan…"
          disabled={busy}
          className="w-40 bg-slate-900 border border-slate-700 text-slate-200 text-[11px] rounded px-2 py-1 disabled:opacity-50"
        />
        <button
          onClick={async () => {
            if (!note.trim()) return;
            setBusy(true);
            await onAction(event.id, note.trim());
            setBusy(false);
          }}
          disabled={busy || !note.trim()}
          className="p-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
        </button>
        <button onClick={() => onDelete(event.id)} title="Hapus (duplikat)" className="p-1.5 bg-slate-800 hover:bg-red-950/60 text-slate-500 hover:text-red-400 rounded"><Trash2 size={13} /></button>
      </div>
    );
  }

  if (event.action_taken) {
    return <span className="text-emerald-400 text-[11px]">{event.action_note}</span>;
  }
  if (event.status === 'DELETED') {
    return <span className="text-slate-500 text-[11px]">{event.delete_reason}</span>;
  }
  return <span className="text-slate-600 text-[11px]">—</span>;
}

const URGENCY_RANK = { critical: 0, warning: 1, info: 2 };
// action-oriented filters surface the most urgent, longest-waiting item first;
// browsing filters (all / already resolved) read naturally newest-first
const ACTION_ORIENTED_FILTERS = new Set(['PENDING', 'AWAITING_ACTION', 'CRITICAL_OPEN']);

export default function Incidents() {
  const [events, setEvents] = useState([]);
  const [quickFilter, setQuickFilter] = useState('ALL');
  const [zoneFilter, setZoneFilter] = useState('ALL');
  const [query, setQuery] = useState('');
  const [feedback, setFeedback] = useState(null);

  const [reportFormat, setReportFormat] = useState('pdf');
  const [reportHours, setReportHours] = useState(24);
  const [reportBusy, setReportBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [eRes, fRes] = await Promise.all([
        fetch(`${API_BASE}/api/events`),
        fetch(`${API_BASE}/api/system/agent-feedback`),
      ]);
      const e = await eRes.json();
      const f = await fRes.json();
      if (e.status === 'success') setEvents(e.events || []);
      setFeedback(f);
    } catch {
      /* keep last known list on transient failure */
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 2000);
    return () => clearInterval(interval);
  }, [refresh]);

  const zones = [...new Set(events.map((e) => e.zone))];
  const activeFilter = QUICK_FILTERS.find((f) => f.id === quickFilter) || QUICK_FILTERS[0];

  const filtered = events
    .filter((e) => {
      if (!activeFilter.match(e)) return false;
      if (zoneFilter !== 'ALL' && e.zone !== zoneFilter) return false;
      if (query.trim()) {
        const q = query.trim().toLowerCase();
        const hay = `${e.seq} ${e.class} ${e.zone}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    })
    .sort((a, b) => {
      if (!ACTION_ORIENTED_FILTERS.has(quickFilter)) return b.ts_ms - a.ts_ms;
      const ra = URGENCY_RANK[a.urgency] ?? 3;
      const rb = URGENCY_RANK[b.urgency] ?? 3;
      if (ra !== rb) return ra - rb;
      return a.ts_ms - b.ts_ms;
    });

  const verify = async (id, status) => {
    await fetch(`${API_BASE}/api/events/${id}/verify`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }),
    });
    refresh();
  };
  const recordAction = async (id, note) => {
    await fetch(`${API_BASE}/api/events/${id}/action`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action_note: note }),
    });
    refresh();
  };
  const deleteEvent = async (id) => {
    await fetch(`${API_BASE}/api/events/${id}/delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: 'Duplikat' }),
    });
    refresh();
  };

  const downloadReport = async () => {
    setReportBusy(true);
    try {
      const zoneQ = zoneFilter !== 'ALL' ? `&zone=${encodeURIComponent(zoneFilter)}` : '';
      window.open(`${API_BASE}/api/reports/generate?format=${reportFormat}&since_hours=${reportHours}${zoneQ}`, '_blank');
    } finally {
      setReportBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <ClipboardList size={20} className="text-blue-400" /> Manajemen Insiden & Laporan
          </h1>
          <p className="text-xs text-slate-400 mt-1">Kelola seluruh siklus insiden dan unduh laporan dalam satu tempat.</p>
        </div>
      </div>

      <div>
        <p className="text-[10px] font-semibold text-slate-500 uppercase mb-2">Filter Cepat</p>
        <div className="flex flex-wrap gap-2">
          {QUICK_FILTERS.map((f) => {
            const count = events.filter(f.match).length;
            const active = quickFilter === f.id;
            const Icon = f.icon;
            return (
              <button
                key={f.id}
                onClick={() => setQuickFilter(f.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors ${
                  active
                    ? 'bg-blue-600 border-blue-500 text-white'
                    : 'bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-600 hover:text-slate-200'
                }`}
              >
                <Icon size={13} /> {f.label}
                <span className={`font-mono text-[10px] px-1.5 rounded-full ${active ? 'bg-white/20' : 'bg-slate-800 text-slate-400'}`}>{count}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <select value={zoneFilter} onChange={(e) => setZoneFilter(e.target.value)} className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded px-2 py-1.5">
              <option value="ALL">Semua Zona</option>
              {zones.map((z) => <option key={z} value={z}>{z}</option>)}
            </select>
            <div className="relative flex-1 min-w-[160px]">
              <Search size={12} className="absolute left-2.5 top-2.5 text-slate-500" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Cari nomor / kelas / zona…"
                className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded pl-7 pr-2 py-1.5"
              />
            </div>
          </div>

          {ACTION_ORIENTED_FILTERS.has(quickFilter) && filtered.length > 0 && (
            <p className="text-[10px] text-slate-600 mb-2">Diurutkan: kritis & menunggu paling lama dulu.</p>
          )}

          <div className="overflow-y-auto max-h-[560px]">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="text-left text-slate-500 uppercase text-[10px] border-b border-slate-800">
                  <th className="py-2 pr-2">#</th>
                  <th className="py-2 pr-2">Waktu</th>
                  <th className="py-2 pr-2">Zona</th>
                  <th className="py-2 pr-2">Kelas</th>
                  <th className="py-2 pr-2">Urgensi</th>
                  <th className="py-2 pr-2">Status</th>
                  <th className="py-2 pr-2">AI</th>
                  <th className="py-2">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr><td colSpan={8} className="text-center text-slate-500 py-8">Tidak ada insiden yang cocok.</td></tr>
                )}
                {filtered.map((e) => (
                  <tr key={e.id} className="border-b border-slate-800/60 hover:bg-slate-950/40">
                    <td className="py-2 pr-2 font-mono text-slate-500"><Hash size={9} className="inline" />{e.seq}</td>
                    <td className="py-2 pr-2 font-mono text-slate-500">{e.timestamp}</td>
                    <td className="py-2 pr-2 text-slate-300"><MapPin size={10} className="inline mr-1 opacity-60" />{e.zone}</td>
                    <td className="py-2 pr-2 font-semibold text-slate-200">{e.class}</td>
                    <td className="py-2 pr-2">
                      {e.urgency && URGENCY_META[e.urgency] && (
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${URGENCY_META[e.urgency].cls}`}>{URGENCY_META[e.urgency].label}</span>
                      )}
                    </td>
                    <td className="py-2 pr-2">
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${STATUS_META[e.status]?.cls || ''}`}>{STATUS_META[e.status]?.label || e.status}</span>
                    </td>
                    <td className="py-2 pr-2">
                      {e.verified_by === 'agent' && (
                        <span title={e.agent_reasoning} className="text-purple-300 flex items-center gap-0.5"><Radar size={11} />{e.agent_verdict}</span>
                      )}
                    </td>
                    <td className="py-2">
                      <ActionCell event={e} onVerify={verify} onAction={recordAction} onDelete={deleteEvent} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <FileDown size={16} className="text-blue-400" /> Unduh Laporan
            </h2>
            <div className="space-y-3">
              <div>
                <label className="text-[10px] font-semibold text-slate-500 uppercase block mb-1">Format</label>
                <div className="flex gap-1.5">
                  {['pdf', 'xlsx', 'csv'].map((f) => (
                    <button
                      key={f}
                      onClick={() => setReportFormat(f)}
                      className={`px-3 py-1.5 rounded text-xs font-semibold border ${reportFormat === f ? 'bg-blue-600/20 border-blue-500/40 text-blue-300' : 'bg-slate-950 border-slate-700 text-slate-400'}`}
                    >
                      {f.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-[10px] font-semibold text-slate-500 uppercase block mb-1">Periode</label>
                <select value={reportHours} onChange={(e) => setReportHours(e.target.value)} className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded px-2 py-1.5">
                  <option value={24}>24 jam terakhir</option>
                  <option value={168}>7 hari terakhir</option>
                  <option value={720}>30 hari terakhir</option>
                </select>
              </div>
              <p className="text-[10px] text-slate-500">Zona mengikuti filter tabel di kiri ({zoneFilter === 'ALL' ? 'semua zona' : zoneFilter}).</p>
              <button
                onClick={downloadReport}
                disabled={reportBusy}
                className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold py-2 rounded-md text-sm"
              >
                {reportBusy ? <Loader2 size={14} className="animate-spin" /> : <FileDown size={14} />} Unduh {reportFormat.toUpperCase()}
              </button>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <TrendingUp size={16} className="text-purple-400" /> Akurasi Mode Otonom
            </h2>
            {feedback && feedback.agent_confirmed > 0 ? (
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-2">
                  <p className="text-[9px] text-slate-500 uppercase">Akurasi</p>
                  <p className="font-mono font-bold text-sm text-purple-300">{feedback.accuracy != null ? `${Math.round(feedback.accuracy * 100)}%` : '—'}</p>
                </div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-2">
                  <p className="text-[9px] text-slate-500 uppercase">Di-CONFIRM</p>
                  <p className="font-mono font-bold text-sm text-slate-200">{feedback.agent_confirmed}</p>
                </div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-2">
                  <p className="text-[9px] text-slate-500 uppercase">Koreksi</p>
                  <p className="font-mono font-bold text-sm text-amber-300">{feedback.mistakes}</p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500">Belum ada data — aktifkan mode otonom di Settings.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
