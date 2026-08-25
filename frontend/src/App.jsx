import { useState, useEffect, useRef, useCallback } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { Activity, BarChart, Settings, Video, LogOut, Cpu, Wifi, WifiOff, Bot } from 'lucide-react';
import LiveMonitor from './pages/LiveMonitor';
import Analytics from './pages/Analytics';
import Configuration from './pages/Settings';
import AgentChat from './pages/AgentChat';
import Login from './pages/Login';
import { AgentChatProvider } from './context/AgentChatContext';
import AgentWidget from './components/AgentWidget';

const API_BASE = 'http://127.0.0.1:8000';

function NavLink({ to, icon: Icon, label }) {
  const location = useLocation();
  const isActive = location.pathname === to;
  
  return (
    <Link 
      to={to} 
      className={`flex items-center gap-2 px-4 py-1.5 rounded-md text-xs font-semibold transition ${
        isActive ? 'bg-blue-600 text-white shadow' : 'text-slate-400 hover:text-white'
      }`}
    >
      <Icon size={14} /> {label}
    </Link>
  );
}

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  // Incident lists are now DERIVED from the backend's /api/events on every poll — the
  // backend event's `status` (PENDING/CONFIRMED/DISMISSED) is the single source of
  // truth, not client-side click history. This also means a dismissed/confirmed event
  // can never "come back" on remount/navigation, since we're not doing incremental
  // "seen" tracking anymore, just re-rendering the backend's current state each tick.
  const [pendingIncidents, setPendingIncidents] = useState([]);
  const [verifiedIncidents, setVerifiedIncidents] = useState([]);

  const mapEvent = (e) => ({
    id: e.id,
    seq: e.seq,
    time: e.timestamp,
    tsMs: e.ts_ms,
    type: (e.class || '').toUpperCase(),
    zone: e.zone,
    eventType: e.type, // VIOLATION | EMERGENCY
    streamId: e.stream_id,
    confidence: e.confidence,
    status: e.status,
    actionTaken: e.action_taken,
    actionNote: e.action_note,
    actionAt: e.action_at,
    urgency: e.urgency,           // info | warning | critical (per-zone per-class)
    verifiedBy: e.verified_by,    // "agent" when confirmed by autonomous handling
    agentVerdict: e.agent_verdict, // real | false | uncertain (autonomous opinion)
    agentReasoning: e.agent_reasoning,
  });

  const refreshIncidents = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/events`);
      const data = await res.json();
      if (data.status !== 'success' || !Array.isArray(data.events)) return;
      setPendingIncidents(data.events.filter((e) => e.status === 'PENDING').map(mapEvent));
      setVerifiedIncidents(data.events.filter((e) => e.status === 'CONFIRMED').map(mapEvent));
    } catch {
      /* keep last known list on transient failure */
    }
  }, []);

  // Backend connectivity + active model, polled from the edge node
  const [backendOnline, setBackendOnline] = useState(false);
  const [modelLabel, setModelLabel] = useState(null);

  useEffect(() => {
    if (!isLoggedIn) return;

    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/models`);
        const data = await res.json();
        if (cancelled) return;
        setBackendOnline(true);
        const active = data.models?.find((m) => m.id === data.active);
        setModelLabel(active ? active.label : data.active);
      } catch {
        if (cancelled) return;
        setBackendOnline(false);
      }
    };

    poll();
    const interval = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [isLoggedIn]);

  useEffect(() => {
    if (!isLoggedIn) return;
    refreshIncidents();
    const interval = setInterval(refreshIncidents, 1000);
    return () => clearInterval(interval);
  }, [isLoggedIn, refreshIncidents]);

  if (!isLoggedIn) {
    return <Login onLogin={() => setIsLoggedIn(true)} />;
  }

  return (
    <BrowserRouter>
      <AgentChatProvider>
      <div className="min-h-screen bg-slate-950 text-slate-100 font-sans">
        
        <header className="bg-slate-900 border-b border-slate-800 px-6 py-4 flex justify-between items-center shadow-lg">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-600/20 border border-blue-500/30 rounded-lg">
              <Activity className="text-blue-400" size={24} />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-wide text-white">SMART FACTORY HSE COMMAND</h1>
              <p className="text-xs text-slate-400">Autonomous Safety Surveillance & Incident Workflow</p>
            </div>
          </div>

          <div className="flex items-center gap-2 bg-slate-950 p-1 rounded-lg border border-slate-800">
            <NavLink to="/" icon={Video} label="Live Monitor" />
            <NavLink to="/analytics" icon={BarChart} label="Analytics" />
            <NavLink to="/agent" icon={Bot} label="AI Agent" />
            <NavLink to="/settings" icon={Settings} label="Settings" />
          </div>

          <div className="flex items-center gap-3 text-xs">
            {modelLabel && (
              <span className="flex items-center gap-1.5 px-3 py-1 bg-slate-950 border border-slate-700 rounded-full text-slate-300 font-mono">
                <Cpu size={13} className="text-blue-400" /> {modelLabel}
              </span>
            )}
            {backendOnline ? (
              <span className="flex items-center gap-2 px-3 py-1 bg-emerald-950/50 border border-emerald-500/30 rounded-full text-emerald-400">
                <Wifi size={13} />
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span> Backend Online
              </span>
            ) : (
              <span className="flex items-center gap-2 px-3 py-1 bg-red-950/50 border border-red-500/30 rounded-full text-red-400">
                <WifiOff size={13} />
                <span className="w-2 h-2 rounded-full bg-red-500"></span> Backend Offline
              </span>
            )}
            <button
              onClick={() => setIsLoggedIn(false)}
              className="flex items-center gap-1 text-slate-400 hover:text-red-400 transition-colors ml-2"
            >
              <LogOut size={14} /> Logout
            </button>
          </div>
        </header>

        <main className="p-6">
          <Routes>
            <Route
              path="/"
              element={
                <LiveMonitor
                  pendingIncidents={pendingIncidents}
                  verifiedIncidents={verifiedIncidents}
                  refreshIncidents={refreshIncidents}
                />
              }
            />
            <Route
              path="/analytics"
              element={<Analytics verifiedIncidents={verifiedIncidents} />}
            />
            <Route path="/agent" element={<AgentChat />} />
            <Route path="/settings" element={<Configuration />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>

        <AgentWidget />
      </div>
      </AgentChatProvider>
    </BrowserRouter>
  );
}