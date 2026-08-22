import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { Activity, BarChart, Settings, Video, LogOut, Cpu, Wifi, WifiOff } from 'lucide-react';
import LiveMonitor from './pages/LiveMonitor';
import Analytics from './pages/Analytics';
import Configuration from './pages/Settings';
import Login from './pages/Login';

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

  // Lifted State: This memory persists even when navigating away from the Live Monitor
  const [pendingIncidents, setPendingIncidents] = useState([]);
  const [verifiedIncidents, setVerifiedIncidents] = useState([]);

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

  if (!isLoggedIn) {
    return <Login onLogin={() => setIsLoggedIn(true)} />;
  }

  return (
    <BrowserRouter>
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
            {/* THIS ROUTE MUST HAVE ALL 4 PROPS */}
            <Route 
              path="/" 
              element={
                <LiveMonitor 
                  pendingIncidents={pendingIncidents} 
                  setPendingIncidents={setPendingIncidents}
                  verifiedIncidents={verifiedIncidents}
                  setVerifiedIncidents={setVerifiedIncidents}
                />
              } 
            />
            <Route 
              path="/analytics" 
              element={<Analytics verifiedIncidents={verifiedIncidents} />} 
            />
            <Route path="/settings" element={<Configuration />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>

      </div>
    </BrowserRouter>
  );
}