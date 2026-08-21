import { useState } from 'react';
import { Activity, Lock } from 'lucide-react';

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (username === 'admin' && password === 'admin') {
      onLogin();
    } else {
      setError('Invalid credentials. Use admin/admin.');
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center font-sans text-slate-100">
      <div className="bg-slate-900 p-8 rounded-xl border border-slate-800 shadow-2xl w-96">
        <div className="flex flex-col items-center gap-3 mb-8">
          <div className="p-3 bg-blue-600/20 border border-blue-500/30 rounded-lg">
            <Activity className="text-blue-400" size={32} />
          </div>
          <h1 className="text-xl font-bold tracking-wide text-white text-center">
            SMART FACTORY<br/>HSE COMMAND
          </h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Username</label>
            <input 
              type="text" 
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-md focus:ring-blue-500 focus:border-blue-500 p-2.5"
              placeholder="Enter username"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Password</label>
            <input 
              type="password" 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-md focus:ring-blue-500 focus:border-blue-500 p-2.5"
              placeholder="Enter password"
            />
          </div>
          
          {error && <p className="text-red-400 text-xs font-semibold">{error}</p>}
          
          <button 
            type="submit" 
            className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-md flex items-center justify-center gap-2 transition-colors mt-4"
          >
            <Lock size={16} /> Login
          </button>
        </form>
      </div>
    </div>
  );
}