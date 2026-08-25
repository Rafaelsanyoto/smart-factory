import { useState } from 'react';
import { Activity, Lock, User, AlertCircle, Info } from 'lucide-react';

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (username === 'admin' && password === 'admin') {
      onLogin();
    } else {
      setError('Nama pengguna atau kata sandi salah.');
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center font-sans text-slate-100">
      <div className="bg-slate-900 p-8 rounded-xl border border-slate-800 shadow-2xl w-96">
        <div className="flex flex-col items-center gap-3 mb-8">
          <div className="p-3 bg-blue-600/20 border border-blue-500/30 rounded-lg">
            <Activity className="text-blue-400" size={32} />
          </div>
          <h1 className="text-2xl font-bold tracking-wide text-white text-center">SafeSight AI</h1>
          <p className="text-[11px] text-slate-500 uppercase tracking-widest">Smart Factory HSE Command</p>
          <p className="text-xs text-slate-500 mt-1">Masuk untuk mengakses dashboard pemantauan</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Nama Pengguna</label>
            <div className="relative">
              <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-md focus:ring-blue-500 focus:border-blue-500 py-2.5 pl-9 pr-3"
                placeholder="Masukkan nama pengguna"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Kata Sandi</label>
            <div className="relative">
              <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-md focus:ring-blue-500 focus:border-blue-500 py-2.5 pl-9 pr-3"
                placeholder="Masukkan kata sandi"
              />
            </div>
          </div>

          {error && (
            <p className="text-red-400 text-xs font-semibold flex items-center gap-1.5">
              <AlertCircle size={13} /> {error}
            </p>
          )}

          <button
            type="submit"
            className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-md flex items-center justify-center gap-2 transition-colors mt-4"
          >
            <Lock size={16} /> Masuk
          </button>
        </form>

        <p className="text-[11px] text-slate-600 flex items-center justify-center gap-1.5 mt-5">
          <Info size={11} /> Demo: nama pengguna <span className="font-mono text-slate-500">admin</span>, kata sandi <span className="font-mono text-slate-500">admin</span>
        </p>
      </div>
    </div>
  );
}
