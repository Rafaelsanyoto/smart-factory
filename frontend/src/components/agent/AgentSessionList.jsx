import { Plus, Trash2, MessageSquare } from 'lucide-react';

function timeAgo(ts) {
  const diffMin = Math.floor((Date.now() - ts) / 60000);
  if (diffMin < 1) return 'baru saja';
  if (diffMin < 60) return `${diffMin}m lalu`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}j lalu`;
  return `${Math.floor(diffH / 24)}h lalu`;
}

export default function AgentSessionList({ sessions, activeId, onSwitch, onNew, onDelete, compact }) {
  return (
    <div className="flex flex-col h-full">
      <button
        onClick={onNew}
        className="flex items-center gap-2 px-3 py-2 mb-2 rounded-lg border border-slate-700 text-slate-300 hover:border-blue-500 hover:text-blue-300 text-xs font-semibold transition-colors"
      >
        <Plus size={13} /> Percakapan Baru
      </button>

      <div className="flex-1 overflow-y-auto space-y-1 pr-0.5">
        {sessions.length === 0 && (
          <p className="text-[11px] text-slate-600 text-center py-6">Belum ada riwayat percakapan.</p>
        )}
        {sessions.map((s) => (
          <div
            key={s.id}
            onClick={() => onSwitch(s.id)}
            className={`group flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer text-xs transition-colors ${
              s.id === activeId ? 'bg-blue-600/15 border border-blue-500/30 text-blue-200' : 'border border-transparent hover:bg-slate-800/60 text-slate-400'
            }`}
          >
            <MessageSquare size={12} className="shrink-0 opacity-60" />
            <div className="min-w-0 flex-1">
              <p className="truncate">{s.title || 'Percakapan baru'}</p>
              {!compact && <p className="text-[10px] text-slate-600">{timeAgo(s.createdAt)} · {s.messages.length} pesan</p>}
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(s.id); }}
              className="shrink-0 opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-opacity"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
