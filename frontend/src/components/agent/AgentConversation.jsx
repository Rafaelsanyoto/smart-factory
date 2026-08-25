import {
  Bot, User, Loader2, CheckCircle, XCircle, Zap, Sparkles,
  Search, CheckCircle2, BrainCircuit, ShieldAlert, FileDown,
} from 'lucide-react';

const API_BASE = 'http://127.0.0.1:8000';

function StepRow({ step }) {
  if (step.step === 'thinking') {
    return (
      <div className="flex items-center gap-2 text-slate-500">
        <BrainCircuit size={12} className="text-blue-400" />
        <span>Berpikir… (langkah {step.round})</span>
      </div>
    );
  }
  if (step.step === 'tool_call') {
    return (
      <div className="flex items-center gap-2 text-slate-400">
        <Search size={12} className="text-amber-400" />
        <span>{step.label}</span>
        {step.args && Object.keys(step.args).length > 0 && (
          <span className="font-mono text-[10px] text-slate-600">{JSON.stringify(step.args)}</span>
        )}
      </div>
    );
  }
  if (step.step === 'tool_result') {
    return (
      <div className="flex items-center gap-2 text-slate-500">
        <CheckCircle2 size={12} className="text-emerald-500" />
        <span>{step.summary}</span>
      </div>
    );
  }
  if (step.step === 'action_call') {
    return (
      <div className="flex items-center gap-2 text-orange-400">
        <ShieldAlert size={12} className="text-orange-400" />
        <span>Aksi otomatis: {step.label}</span>
        {step.args && Object.keys(step.args).length > 0 && (
          <span className="font-mono text-[10px] text-slate-600">{JSON.stringify(step.args)}</span>
        )}
      </div>
    );
  }
  if (step.step === 'action_result') {
    return (
      <div className="flex items-center gap-2 text-orange-300">
        <CheckCircle2 size={12} className="text-orange-400" />
        <span>{step.summary}</span>
      </div>
    );
  }
  return null;
}

export function LoadingState({ compact }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center text-slate-500 gap-2 py-6">
      <Loader2 size={compact ? 20 : 28} className="animate-spin text-slate-600" />
      <p className="text-xs">Memuat riwayat percakapan…</p>
    </div>
  );
}

export function EmptyState({ suggestions = [], onPick, disabled, compact }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center text-slate-500 gap-3 py-6">
      <Sparkles size={compact ? 22 : 32} className="text-slate-700" />
      <p className="text-xs max-w-xs">Mulai dengan salah satu contoh di bawah, atau ketik pertanyaanmu sendiri.</p>
      <div className="flex flex-wrap gap-2 justify-center max-w-md px-2">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            disabled={disabled}
            className="text-[11px] px-3 py-1.5 rounded-full border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors disabled:opacity-40"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function AgentConversation({ messages, sessionId, onResolveAction, compact }) {
  const avatarSize = compact ? 26 : 32;
  const iconSize = compact ? 13 : 15;

  return (
    <>
      {messages.map((m) => (
        <div key={m.id} className={`flex gap-2.5 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
          <div
            style={{ width: avatarSize, height: avatarSize }}
            className={`shrink-0 rounded-lg flex items-center justify-center border ${
              m.role === 'user'
                ? 'bg-blue-600/20 border-blue-500/30 text-blue-400'
                : 'bg-slate-800 border-slate-700 text-slate-300'
            }`}
          >
            {m.role === 'user' ? <User size={iconSize} /> : <Bot size={iconSize} />}
          </div>

          <div className={`max-w-[85%] space-y-2 ${m.role === 'user' ? 'items-end flex flex-col' : ''}`}>
            {m.role === 'agent' && m.steps && m.steps.length > 0 && (
              <div className="px-3 py-2 rounded-xl bg-slate-950/60 border border-slate-800/80 text-[11px] space-y-1.5 font-mono">
                {m.steps.map((s, idx) => <StepRow key={idx} step={s} />)}
                {m.streaming && (
                  <div className="flex items-center gap-2 text-blue-400">
                    <Loader2 size={12} className="animate-spin" />
                    <span>Menyusun jawaban…</span>
                  </div>
                )}
              </div>
            )}

            {m.role === 'agent' && m.streaming && (!m.steps || m.steps.length === 0) && (
              <div className="px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-400 text-sm flex items-center gap-2">
                <Loader2 size={13} className="animate-spin" /> Menganalisa…
              </div>
            )}

            {m.text && (
              <div
                className={`px-3 py-2 rounded-xl text-sm leading-relaxed whitespace-pre-wrap ${
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

            {m.reports && m.reports.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {m.reports.map((r) => (
                  <a
                    key={r.filename}
                    href={r.download_url || `${API_BASE}/api/reports/file/${r.filename}`}
                    download
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600/15 border border-blue-500/40 text-blue-300 hover:bg-blue-600/25 text-xs font-semibold transition-colors"
                  >
                    <FileDown size={14} /> Unduh {(r.format || 'file').toUpperCase()}
                  </a>
                ))}
              </div>
            )}

            {m.pendingAction && (
              <div className="bg-slate-950 border border-amber-500/40 rounded-xl p-3 space-y-2.5 w-full">
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
                      onClick={() => onResolveAction(sessionId, m.id, false)}
                      className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs flex items-center gap-1.5"
                    >
                      <XCircle size={14} /> Batal
                    </button>
                    <button
                      onClick={() => onResolveAction(sessionId, m.id, true)}
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
    </>
  );
}
