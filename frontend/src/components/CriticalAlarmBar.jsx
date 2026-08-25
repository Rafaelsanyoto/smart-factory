import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Flame, CheckCircle, X, Hash, MapPin, BellRing } from 'lucide-react';
import { playAlarmBeep } from '../lib/alarmSound';

const API_BASE = 'http://127.0.0.1:8000';
const BEEP_INTERVAL_MS = 2500;
const REMINDER_POPUP_INTERVAL_MS = 2 * 60 * 1000;

export default function CriticalAlarmBar({ incidents = [], onChanged }) {
  const criticalOpen = incidents.filter((i) => i.urgency === 'critical' && !i.actionTaken);
  const unacked = criticalOpen.filter((i) => !i.alarmAckAt);
  const acked = criticalOpen.filter((i) => i.alarmAckAt);

  const [popupOpen, setPopupOpen] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const popupTimer = useRef(null);

  useEffect(() => {
    if (unacked.length === 0) return undefined;
    playAlarmBeep();
    const interval = setInterval(playAlarmBeep, BEEP_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [unacked.length]);

  useEffect(() => {
    if (acked.length === 0 || unacked.length > 0) {
      setPopupOpen(false);
      if (popupTimer.current) clearInterval(popupTimer.current);
      return undefined;
    }
    setPopupOpen(true);
    popupTimer.current = setInterval(() => setPopupOpen(true), REMINDER_POPUP_INTERVAL_MS);
    return () => clearInterval(popupTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [acked.length > 0, unacked.length > 0]);

  const acknowledge = async (id) => {
    setBusyId(id);
    try {
      await fetch(`${API_BASE}/api/events/${id}/acknowledge`, { method: 'POST' });
    } finally {
      setBusyId(null);
      if (typeof onChanged === 'function') onChanged();
    }
  };

  if (criticalOpen.length === 0) return null;

  return (
    <>
      {unacked.length > 0 && (
        <div className="bg-red-950 border-b-2 border-red-500 px-6 py-3 shadow-xl">
          <div className="flex items-start gap-3">
            <Flame size={22} className="text-red-400 shrink-0 mt-0.5 animate-pulse" />
            <div className="flex-1 space-y-2">
              <p className="text-sm font-bold text-red-200 tracking-wide">
                {unacked.length === 1 ? 'KONDISI KRITIS TERDETEKSI' : `${unacked.length} KONDISI KRITIS TERDETEKSI`} — perlu konfirmasi
              </p>
              <div className="flex flex-wrap gap-2">
                {unacked.map((inc) => (
                  <div key={inc.id} className="flex items-center gap-2 bg-red-900/60 border border-red-700/60 rounded-lg pl-3 pr-1.5 py-1.5 text-xs text-red-100">
                    <Hash size={11} className="opacity-70" />{inc.seq ?? '?'}
                    <span className="font-semibold">{inc.type}</span>
                    <span className="flex items-center gap-1 opacity-80"><MapPin size={10} />{inc.zone}</span>
                    <button
                      onClick={() => acknowledge(inc.id)}
                      disabled={busyId === inc.id}
                      className="flex items-center gap-1 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-semibold px-2 py-1 rounded ml-1 transition-colors"
                    >
                      <CheckCircle size={12} /> Sudah Aman
                    </button>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-red-300/70">
                Alarm tidak akan hilang otomatis walau deteksi berhenti — klik "Sudah Aman" untuk mengonfirmasi, lalu catat tindakan penyelesaiannya.
              </p>
            </div>
          </div>
        </div>
      )}

      {popupOpen && acked.length > 0 && unacked.length === 0 && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 px-4">
          <div className="bg-slate-900 border border-amber-500/50 rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-start gap-3">
              <BellRing size={22} className="text-amber-400 shrink-0" />
              <div>
                <p className="text-sm font-bold text-amber-200">Pengingat: Insiden Kritis Belum Selesai</p>
                <p className="text-xs text-slate-400 mt-1">
                  {acked.length === 1 ? 'Insiden ini sudah dikonfirmasi aman' : `${acked.length} insiden sudah dikonfirmasi aman`}, tapi belum ada tindakan yang dicatat. Popup ini akan muncul lagi secara berkala sampai tindakan tercatat.
                </p>
              </div>
            </div>
            <div className="space-y-1.5">
              {acked.map((inc) => (
                <div key={inc.id} className="flex items-center gap-2 text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2">
                  <Hash size={11} className="text-slate-500" />{inc.seq ?? '?'}
                  <span className="font-semibold text-slate-200">{inc.type}</span>
                  <span className="flex items-center gap-1 text-slate-400"><MapPin size={10} />{inc.zone}</span>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setPopupOpen(false)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors"
              >
                <X size={13} /> Tutup
              </button>
              <Link
                to="/"
                onClick={() => setPopupOpen(false)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-md text-xs font-semibold transition-colors"
              >
                Catat Tindakan
              </Link>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
