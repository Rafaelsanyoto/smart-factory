import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const API_BASE = 'http://127.0.0.1:8000';
const STORAGE_KEY = 'hse_agent_sessions_v1';
const ACTIVE_KEY = 'hse_agent_active_session_v1';
const MAX_SESSIONS = 20;

const genId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

function loadSessions() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    // A message still marked "streaming" means the tab was closed/refreshed mid-reply —
    // that stream can never resume, so mark it finished instead of showing a stuck spinner.
    return parsed.map((s) => ({
      ...s,
      messages: (s.messages || []).map((m) =>
        m.streaming ? { ...m, streaming: false, text: m.text || 'Sesi terputus sebelum selesai.' } : m,
      ),
    }));
  } catch {
    return [];
  }
}

function saveSessions(sessions) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, MAX_SESSIONS)));
  } catch {
    /* storage full/unavailable — chat still works, just won't persist */
  }
}

const AgentChatCtx = createContext(null);

export function AgentChatProvider({ children }) {
  const [sessions, setSessions] = useState(() => loadSessions());
  const [activeId, setActiveId] = useState(() => {
    const initial = loadSessions();
    const saved = localStorage.getItem(ACTIVE_KEY);
    if (saved && initial.some((s) => s.id === saved)) return saved;
    return initial[0]?.id || null;
  });
  const [status, setStatus] = useState({ configured: null, channel: null });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/agent/status`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus({ configured: false, channel: null, offline: true }));
  }, []);

  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  useEffect(() => {
    if (activeId) localStorage.setItem(ACTIVE_KEY, activeId);
  }, [activeId]);

  const newSession = useCallback(() => {
    const id = genId();
    setSessions((prev) => [{ id, title: 'Percakapan baru', createdAt: Date.now(), messages: [] }, ...prev].slice(0, MAX_SESSIONS));
    setActiveId(id);
    return id;
  }, []);

  const ensureSession = useCallback(() => {
    let result = activeId;
    setSessions((prev) => {
      if (activeId && prev.some((s) => s.id === activeId)) return prev;
      const id = genId();
      result = id;
      return [{ id, title: 'Percakapan baru', createdAt: Date.now(), messages: [] }, ...prev].slice(0, MAX_SESSIONS);
    });
    if (!activeId || !sessions.some((s) => s.id === activeId)) {
      // result was just assigned inside the updater above (synchronous within this tick)
      setActiveId((prev) => (prev && sessions.some((s) => s.id === prev) ? prev : result));
    }
    return result;
  }, [activeId, sessions]);

  const switchSession = useCallback((id) => setActiveId(id), []);

  const deleteSession = useCallback((id) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setActiveId((prev) => (prev === id ? null : prev));
  }, []);

  const patchSessionMessages = useCallback((sessionId, updater) => {
    setSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, messages: updater(s.messages) } : s)));
  }, []);

  const patchMessage = useCallback(
    (sessionId, msgId, patch) => {
      patchSessionMessages(sessionId, (msgs) =>
        msgs.map((m) => (m.id === msgId ? { ...m, ...(typeof patch === 'function' ? patch(m) : patch) } : m)),
      );
    },
    [patchSessionMessages],
  );

  const sendMessage = useCallback(
    async (text) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;

      const sessionId = ensureSession();
      const priorMessages = sessions.find((s) => s.id === sessionId)?.messages || [];

      const userMsg = { id: genId(), role: 'user', text: trimmed };
      const agentId = genId();
      const agentMsg = { id: agentId, role: 'agent', text: '', steps: [], streaming: true, pendingAction: null, actionState: null };

      patchSessionMessages(sessionId, (msgs) => [...msgs, userMsg, agentMsg]);
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId && s.title === 'Percakapan baru' ? { ...s, title: trimmed.slice(0, 48) } : s)),
      );
      setLoading(true);

      const history = [...priorMessages, userMsg]
        .filter((m) => m.text)
        .map((m) => ({ role: m.role === 'user' ? 'user' : 'agent', text: m.text }));

      try {
        const res = await fetch(`${API_BASE}/api/agent/chat/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: history }),
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

            if (step.step === 'thinking' || step.step === 'tool_call' || step.step === 'tool_result') {
              patchMessage(sessionId, agentId, (m) => ({ steps: [...m.steps, step] }));
              continue;
            }

            patchMessage(sessionId, agentId, {
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
        patchMessage(sessionId, agentId, { text: 'Gagal terhubung ke backend.', error: true, streaming: false });
      } finally {
        setLoading(false);
      }
    },
    [loading, ensureSession, sessions, patchSessionMessages, patchMessage],
  );

  const resolveAction = useCallback(
    async (sessionId, msgId, approve) => {
      const session = sessions.find((s) => s.id === sessionId);
      const msg = session?.messages.find((m) => m.id === msgId);
      if (!msg?.pendingAction) return;

      if (!approve) {
        patchMessage(sessionId, msgId, { actionState: 'cancelled' });
        return;
      }

      patchMessage(sessionId, msgId, { actionState: 'running' });
      try {
        const res = await fetch(`${API_BASE}/api/agent/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tool: msg.pendingAction.tool, args: msg.pendingAction.args }),
        });
        const data = await res.json();
        const ok = data.status === 'success' && data.result?.status !== 'error';
        const detail = data.result?.message || data.message || (ok ? 'Aksi berhasil dijalankan.' : 'Aksi gagal.');
        patchMessage(sessionId, msgId, { actionState: ok ? 'done' : 'failed', actionResult: detail });
      } catch {
        patchMessage(sessionId, msgId, { actionState: 'failed', actionResult: 'Gagal menghubungi backend.' });
      }
    },
    [sessions, patchMessage],
  );

  const activeSession = sessions.find((s) => s.id === activeId) || null;

  const value = {
    sessions,
    activeId,
    activeSession,
    status,
    loading,
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
