import { useState, useRef, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { Bot, X, History, ArrowUpRight, AlertTriangle, WifiOff } from 'lucide-react';
import { useAgentChat } from '../context/AgentChatContext';
import AgentConversation, { EmptyState, LoadingState } from './agent/AgentConversation';
import AgentComposer from './agent/AgentComposer';
import AgentSessionList from './agent/AgentSessionList';

const SUGGESTIONS = [
  'Ada pelanggaran apa 10 menit terakhir?',
  'Ringkas kondisi keselamatan sekarang.',
];

export default function AgentWidget() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const scrollRef = useRef(null);
  const {
    sessions, activeId, activeSession, status, loading, messagesLoading,
    sendMessage, resolveAction, newSession, switchSession, deleteSession,
  } = useAgentChat();

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [activeSession?.messages, loading, open]);

  // Skip rendering the widget on the dedicated /agent page — it's already the full view.
  if (location.pathname === '/agent') return null;

  const messages = activeSession?.messages || [];
  const notConfigured = status.configured === false;

  return (
    <div className="fixed bottom-5 right-5 z-50">
      {open && (
        <div className="mb-3 w-96 h-[30rem] bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-slate-800 bg-slate-950/60">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <Bot size={16} className="text-blue-400" /> AI Safety Agent
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setShowHistory((v) => !v)}
                title="Riwayat percakapan"
                className={`p-1.5 rounded-md transition-colors ${showHistory ? 'bg-slate-800 text-blue-300' : 'text-slate-400 hover:text-slate-200'}`}
              >
                <History size={14} />
              </button>
              <a
                href="/agent"
                title="Buka halaman penuh"
                className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 transition-colors"
              >
                <ArrowUpRight size={14} />
              </a>
              <button onClick={() => setOpen(false)} className="p-1.5 rounded-md text-slate-400 hover:text-red-400 transition-colors">
                <X size={14} />
              </button>
            </div>
          </div>

          {showHistory ? (
            <div className="flex-1 overflow-hidden p-2.5">
              <AgentSessionList
                sessions={sessions}
                activeId={activeId}
                onSwitch={(id) => { switchSession(id); setShowHistory(false); }}
                onNew={() => { newSession(); setShowHistory(false); }}
                onDelete={deleteSession}
                compact
              />
            </div>
          ) : (
            <>
              {notConfigured && (
                <div className="mx-2.5 mt-2 bg-amber-950/40 border border-amber-500/40 text-amber-300 text-[10px] p-2 rounded-lg flex items-center gap-1.5">
                  <AlertTriangle size={11} /> Isi GEMINI_API_KEY di .env untuk mengaktifkan.
                </div>
              )}
              {status.offline && (
                <div className="mx-2.5 mt-2 bg-red-950/50 border border-red-500/40 text-red-400 text-[10px] p-2 rounded-lg flex items-center gap-1.5">
                  <WifiOff size={11} /> Backend offline.
                </div>
              )}

              <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
                {messagesLoading ? (
                  <LoadingState compact />
                ) : messages.length === 0 ? (
                  <EmptyState suggestions={SUGGESTIONS} onPick={sendMessage} disabled={notConfigured} compact />
                ) : (
                  <AgentConversation messages={messages} sessionId={activeId} onResolveAction={resolveAction} compact />
                )}
              </div>

              <div className="p-2.5 border-t border-slate-800">
                <AgentComposer
                  onSend={sendMessage}
                  disabled={notConfigured || loading}
                  placeholder={notConfigured ? 'Belum dikonfigurasi…' : 'Tanya agent… ("/" untuk saran)'}
                />
              </div>
            </>
          )}
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className={`w-14 h-14 rounded-full shadow-2xl flex items-center justify-center transition-all ${
          open ? 'bg-slate-800 border border-slate-600' : 'bg-blue-600 hover:bg-blue-500'
        }`}
      >
        {open ? <X size={22} className="text-slate-300" /> : <Bot size={24} className="text-white" />}
      </button>
    </div>
  );
}
