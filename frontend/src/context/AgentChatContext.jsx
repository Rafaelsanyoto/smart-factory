import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const API_BASE = 'http://127.0.0.1:8000';
const LAST_ACTIVE_KEY = 'hse_agent_last_active_session'; // just a UI convenience — which
// tab was open last. The actual chat content lives entirely in the backend DB now.

const genId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

// Backend chat_messages row -> the shape the UI components expect.
function mapServerMessage(m) {
  return {
    id: m.id,
    role: m.role,
    text: m.text || '',
    steps: m.steps || [],
    streaming: false,
    pendingAction: m.pending_action || null,
    // Resolution outcome (awaiting/done/failed/cancelled) is persisted on pending_action
    // itself, so reloading a session shows what actually happened instead of resetting.
    actionState: m.pending_action ? (m.pending_action.state || 'awaiting') : null,
    actionResult: m.pending_action?.result || null,
  };
}

const AgentChatCtx = createContext(null);

export function AgentChatProvider({ children }) {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(() => localStorage.getItem(LAST_ACTIVE_KEY) || null);
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState({ configured: null, channel: null });
  const [loading, setLoading] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/agent/status`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus({ configured: false, channel: null, offline: true }));
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agent/sessions`);
      const data = await res.json();
      if (data.status === 'success') setSessions(data.sessions || []);
      return data.sessions || [];
    } catch {
      return [];
    }
  }, []);

  const loadMessages = useCallback(async (sessionId) => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    setMessagesLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/agent/sessions/${sessionId}/messages`);
      const data = await res.json();
      setMessages(data.status === 'success' ? data.messages.map(mapServerMessage) : []);
    } catch {
      setMessages([]);
    } finally {
      setMessagesLoading(false);
    }
  }, []);

  // Initial load: fetch the session list, then load whichever was last active (if it
  // still exists) or the most recent one.
  useEffect(() => {
    (async () => {
      const list = await refreshSessions();
      const stillExists = activeId && list.some((s) => s.id === activeId);
      const initial = stillExists ? activeId : list[0]?.id || null;
      setActiveId(initial);
      if (initial) loadMessages(initial);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (activeId) localStorage.setItem(LAST_ACTIVE_KEY, activeId);
    else localStorage.removeItem(LAST_ACTIVE_KEY);
  }, [activeId]);

  const newSession = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agent/sessions`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        setSessions((prev) => [data.session, ...prev]);
        setActiveId(data.session.id);
        setMessages([]);
        return data.session.id;
      }
    } catch {
      /* backend offline — sendMessage will surface the error */
    }
    return null;
  }, []);

  const switchSession = useCallback(
    (id) => {
      setActiveId(id);
      loadMessages(id);
    },
    [loadMessages],
  );

  const deleteSession = useCallback(
    async (id) => {
      try {
        await fetch(`${API_BASE}/api/agent/sessions/${id}`, { method: 'DELETE' });
      } catch {
        /* ignore — still remove locally so the UI doesn't feel stuck */
      }
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
    },
    [activeId],
  );

  const patchMessage = useCallback((msgId, patch) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, ...(typeof patch === 'function' ? patch(m) : patch) } : m)),
    );
  }, []);

  const sendMessage = useCallback(
    async (text) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;

      const userMsg = { id: genId(), role: 'user', text: trimmed };
      const agentId = genId();
      const agentMsg = { id: agentId, role: 'agent', text: '', steps: [], streaming: true, pendingAction: null, actionState: null };

      setMessages((prev) => [...prev, userMsg, agentMsg]);
      setLoading(true);

      let sessionIdForThisSend = activeId;

      try {
        const res = await fetch(`${API_BASE}/api/agent/chat/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: activeId, text: trimmed }),
        });
        if (!res.ok || !res.body) throw new Error('stream failed');

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();

          for (const line of lines) {
            if (!line.trim()) continue;
            const step = JSON.parse(line);

            if (step.step === 'session') {
              sessionIdForThisSend = step.session_id;
              if (step.session_id !== activeId) {
                setActiveId(step.session_id);
                refreshSessions();
              }
              continue;
            }
            if (step.step === 'thinking' || step.step === 'tool_call' || step.step === 'tool_result' || step.step === 'action_call' || step.step === 'action_result') {
              patchMessage(agentId, (m) => ({ steps: [...m.steps, step] }));
              continue;
            }

            patchMessage(agentId, {
              text: step.reply || '',
              pendingAction: step.pending_action || null,
              actionState: step.pending_action ? 'awaiting' : null,
              streaming: false,
              error: step.step === 'error',
            });
            if (step.configured === false) setStatus((s) => ({ ...s, configured: false }));
          }
        }
      } catch {
        patchMessage(agentId, { text: 'Gagal terhubung ke backend.', error: true, streaming: false });
      } finally {
        setLoading(false);
        refreshSessions(); // picks up the updated title/updated_at for the sidebar
      }
    },
    [loading, activeId, patchMessage, refreshSessions],
  );

  const resolveAction = useCallback(
    async (sessionId, msgId, approve) => {
      const msg = messages.find((m) => m.id === msgId);
      if (!msg?.pendingAction) return;

      // Both approve and cancel go through the backend so the outcome is written to the
      // message row — otherwise reloading the session would show "Awaiting" again even
      // though the action was already run or dismissed.
      patchMessage(msgId, { actionState: approve ? 'running' : 'cancelled' });
      try {
        const res = await fetch(`${API_BASE}/api/agent/messages/${msgId}/resolve-action`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approve }),
        });
        const data = await res.json();
        if (data.pending_action) {
          patchMessage(msgId, {
            pendingAction: data.pending_action,
            actionState: data.pending_action.state || (approve ? 'failed' : 'cancelled'),
            actionResult: data.pending_action.result || null,
          });
        } else {
          patchMessage(msgId, { actionState: 'failed', actionResult: data.message || 'Aksi gagal.' });
        }
      } catch {
        patchMessage(msgId, { actionState: 'failed', actionResult: 'Gagal menghubungi backend.' });
      }
    },
    [messages, patchMessage],
  );

  const activeSession = sessions.find((s) => s.id === activeId) || null;

  const value = {
    sessions,
    activeId,
    activeSession: activeSession ? { ...activeSession, messages } : (activeId ? { id: activeId, messages } : null),
    status,
    loading,
    messagesLoading,
    sendMessage,
    resolveAction,
    newSession,
    switchSession,
    deleteSession,
  };

  return <AgentChatCtx.Provider value={value}>{children}</AgentChatCtx.Provider>;
}

export function useAgentChat() {
  const ctx = useContext(AgentChatCtx);
  if (!ctx) throw new Error('useAgentChat must be used within AgentChatProvider');
  return ctx;
}
