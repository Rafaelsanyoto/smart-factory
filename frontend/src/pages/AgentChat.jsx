import { useState, useEffect, useRef } from 'react';
import {
  Bot, Send, User, Loader2, CheckCircle, XCircle, Zap, WifiOff, AlertTriangle, Sparkles,
} from 'lucide-react';

const API_BASE = 'http://127.0.0.1:8000';

const SUGGESTIONS = [
  'Ada pelanggaran apa saja dalam 10 menit terakhir?',
  'Zona mana yang paling sering pelanggaran hari ini?',
  'Ringkas kondisi keselamatan pabrik sekarang.',
  'Kirim ringkasan pelanggaran hari ini ke Telegram.',
];

export default function AgentChat() {
  const [status, setStatus] = useState({ configured: null, telegram: false });
  const [messages, setMessages] = useState([]); // {role:'user'|'agent', text, pendingAction?, actionState?}
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/agent/status`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus({ configured: false, telegram: false, offline: true }));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, loading]);

  const sendMessage = async (textArg) => {
    const text = (textArg ?? input).trim();
    if (!text || loading) return;

    const nextMessages = [...messages, { role: 'user', text }];
    setMessages(nextMessages);
    setInput('');
    setLoading(true);

    // Only user/agent text goes into history (pending-action cards carry no model text)
    const history = nextMessages
      .filter((m) => m.text)
      .map((m) => ({ role: m.role === 'user' ? 'user' : 'agent', text: m.text }));

    try {
      const res = await fetch(`${API_BASE}/api/agent/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history }),
      });
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: 'agent',
          text: data.reply || '',
          pendingAction: data.pending_action || null,
          actionState: data.pending_action ? 'awaiting' : null,
        },
      ]);
    } catch {
      setMessages((prev) => [...prev, { role: 'agent', text: '⚠️ Gagal terhubung ke backend.', error: true }]);
    } finally {
      setLoading(false);
    }
  };

  const resolveAction = async (index, approve) => {
    const msg = messages[index];
    if (!msg?.pendingAction) return;

    if (!approve) {
      setMessages((prev) => prev.map((m, i) => (i === index ? { ...m, actionState: 'cancelled' } : m)));
      return;
    }

    setMessages((prev) => prev.map((m, i) => (i === index ? { ...m, actionState: 'running' } : m)));
    try {
      const res = await fetch(`${API_BASE}/api/agent/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool: msg.pendingAction.tool, args: msg.pendingAction.args }),
      });
      const data = await res.json();
      const ok = data.status === 'success' && data.result?.status !== 'error';
      const detail = data.result?.message || data.message || (ok ? 'Aksi berhasil dijalankan.' : 'Aksi gagal.');
      setMessages((prev) =>
        prev.map((m, i) => (i === index ? { ...m, actionState: ok ? 'done' : 'failed', actionResult: detail } : m)),
      );
    } catch {
      setMessages((prev) =>
        prev.map((m, i) => (i === index ? { ...m, actionState: 'failed', actionResult: 'Gagal menghubungi backend.' } : m)),
      );
    }
  };

  const notConfigured = status.configured === false;

  return (
    <div className="max-w-3xl mx-auto flex flex-col h-[calc(100vh-9rem)]">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Bot size={20} className="text-blue-400" /> AI Safety Agent
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Tanya kondisi keselamatan pabrik atau minta aksi — tiap aksi butuh konfirmasi kamu.
          </p>
        </div>
        <span
          className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono border ${
            status.telegram
              ? 'text-emerald-400 border-emerald-800/50 bg-emerald-950/30'
              : 'text-slate-500 border-slate-800 bg-slate-900'
          }`}
        >
          <Zap size={12} /> Telegram {status.telegram ? 'aktif' : 'off'}
        </span>
      </div>

      {notConfigured && (
        <div className="bg-amber-950/40 border border-amber-500/40 text-amber-300 text-xs p-3 rounded-lg flex items-center gap-2 mb-4">
          <AlertTriangle size={14} />
          AI Agent belum aktif — isi <span className="font-mono">GEMINI_API_KEY</span> di file <span className="font-mono">.env</span>, lalu restart backend.
        </div>
      )}
      {status.offline && (
        <div className="bg-red-950/50 border border-red-500/40 text-red-400 text-xs p-3 rounded-lg flex items-center gap-2 mb-4">
          <WifiOff size={14} /> Backend offline.
        </div>
      )}

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4 shadow-xl"
      >
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center text-slate-500 gap-4">
            <Sparkles size={32} className="text-slate-700" />
            <p className="text-xs max-w-xs">Mulai dengan salah satu contoh di bawah, atau ketik pertanyaanmu sendiri.</p>
            <div className="flex flex-wrap gap-2 justify-center max-w-md">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  disabled={notConfigured}
                  className="text-[11px] px-3 py-1.5 rounded-full border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors disabled:opacity-40"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div
              className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center border ${
                m.role === 'user'
                  ? 'bg-blue-600/20 border-blue-500/30 text-blue-400'
                  : 'bg-slate-800 border-slate-700 text-slate-300'
              }`}
            >
              {m.role === 'user' ? <User size={15} /> : <Bot size={15} />}
            </div>

            <div className={`max-w-[80%] space-y-2 ${m.role === 'user' ? 'items-end flex flex-col' : ''}`}>
              {m.text && (
                <div
                  className={`px-3.5 py-2.5 rounded-xl text-sm leading-relaxed whitespace-pre-wrap ${
                    m.role === 'user'
                      ? 'bg-blue-600 text-white rounded-tr-sm'
                      : m.error
                      ? 'bg-red-950/40 border border-red-800/40 text-red-300 rounded-tl-sm'
                      : 'bg-slate-950 border border-slate-800 text-slate-200 rounded-tl-sm'
                  }`}
                >
                  {m.text}
                </div>
              )}

              {m.pendingAction && (
                <div className="bg-slate-950 border border-amber-500/40 rounded-xl p-3.5 space-y-3 w-full">
                  <div className="flex items-center gap-2 text-amber-300 text-xs font-semibold uppercase tracking-wide">
                    <Zap size={13} /> Konfirmasi Aksi
                  </div>
                  <p className="text-sm text-slate-200 whitespace-pre-wrap">{m.pendingAction.description}</p>
                  <p className="text-[10px] font-mono text-slate-500">
                    {m.pendingAction.tool}({JSON.stringify(m.pendingAction.args)})
                  </p>

                  {m.actionState === 'awaiting' && (
                    <div className="flex gap-2 pt-1">
                      <button
                        onClick={() => resolveAction(i, false)}
                        className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs flex items-center gap-1.5"
                      >
                        <XCircle size={14} /> Batal
                      </button>
                      <button
                        onClick={() => resolveAction(i, true)}
                        className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded text-xs font-semibold flex items-center gap-1.5"
                      >
                        <CheckCircle size={14} /> Jalankan
                      </button>
                    </div>
                  )}
                  {m.actionState === 'running' && (
                    <p className="text-xs text-blue-400 flex items-center gap-1.5"><Loader2 size={13} className="animate-spin" /> Menjalankan…</p>
                  )}
                  {m.actionState === 'done' && (
                    <p className="text-xs text-emerald-400 flex items-center gap-1.5"><CheckCircle size={13} /> {m.actionResult}</p>
                  )}
                  {m.actionState === 'failed' && (
                    <p className="text-xs text-red-400 flex items-center gap-1.5"><XCircle size={13} /> {m.actionResult}</p>
                  )}
                  {m.actionState === 'cancelled' && (
                    <p className="text-xs text-slate-500 flex items-center gap-1.5"><XCircle size={13} /> Dibatalkan.</p>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center border bg-slate-800 border-slate-700 text-slate-300">
              <Bot size={15} />
            </div>
            <div className="px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-400 text-sm flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" /> Menganalisa…
            </div>
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); sendMessage(); }}
        className="mt-4 flex items-center gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={notConfigured || loading}
          placeholder={notConfigured ? 'AI Agent belum dikonfigurasi…' : 'Tanya atau perintahkan agent…'}
          className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 p-3 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={notConfigured || loading || !input.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:hover:bg-blue-600 text-white px-4 py-3 rounded-lg flex items-center gap-2 text-sm font-semibold transition-colors"
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
