import { useEffect, useRef } from 'react';
import { Bot, Zap, AlertTriangle, WifiOff } from 'lucide-react';
import { useAgentChat } from '../context/AgentChatContext';
import AgentConversation, { EmptyState } from '../components/agent/AgentConversation';
import AgentComposer from '../components/agent/AgentComposer';
import AgentSessionList from '../components/agent/AgentSessionList';

const SUGGESTIONS = [
  'Ada pelanggaran apa saja dalam 10 menit terakhir?',
  'Zona mana yang paling sering pelanggaran hari ini?',
  'Ringkas kondisi keselamatan pabrik sekarang.',
  'Kirim ringkasan pelanggaran hari ini ke channel safety.',
];

export default function AgentChatPage() {
  const {
    sessions, activeId, activeSession, status, loading,
    sendMessage, resolveAction, newSession, switchSession, deleteSession,
  } = useAgentChat();
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [activeSession?.messages, loading]);

  const messages = activeSession?.messages || [];
  const notConfigured = status.configured === false;

  return (
    <div className="flex gap-6 h-[calc(100vh-9rem)]">
      <div className="w-64 shrink-0 bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-xl">
        <AgentSessionList
          sessions={sessions}
          activeId={activeId}
          onSwitch={switchSession}
          onNew={newSession}
          onDelete={deleteSession}
        />
      </div>

      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              <Bot size={20} className="text-blue-400" /> AI Safety Agent
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              Tanya kondisi keselamatan pabrik atau minta aksi — tiap aksi butuh konfirmasi kamu. Ketik "/" untuk saran perintah.
            </p>
          </div>
          <span
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono border ${
              status.channel
                ? 'text-emerald-400 border-emerald-800/50 bg-emerald-950/30'
                : 'text-slate-500 border-slate-800 bg-slate-900'
            }`}
          >
            <Zap size={12} /> {status.channel ? `${status.channel} aktif` : 'notif off'}
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
          {messages.length === 0 ? (
            <EmptyState suggestions={SUGGESTIONS} onPick={sendMessage} disabled={notConfigured} />
          ) : (
            <AgentConversation messages={messages} sessionId={activeId} onResolveAction={resolveAction} />
          )}
        </div>

        <div className="mt-4">
          <AgentComposer
            onSend={sendMessage}
            disabled={notConfigured || loading}
            placeholder={notConfigured ? 'AI Agent belum dikonfigurasi…' : 'Tanya atau perintahkan agent…'}
          />
        </div>
      </div>
    </div>
  );
}
