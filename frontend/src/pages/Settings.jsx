import { useState } from 'react';
import { Sliders, Camera, Database, Save, Server, Shield, Trash2, Plus } from 'lucide-react';

export default function Configuration() {
  const [confidence, setConfidence] = useState(0.65);
  const [activeClasses, setActiveClasses] = useState({
    hardhat: true,
    vest: true,
    mask: false,
  });

  const [cameras, setCameras] = useState([
    { id: 'stream_01', label: 'Assembly Line A (Cam 01)' },
    { id: 'stream_02', label: 'Welding Bay B (Cam 02)' }
  ]);

  const [retention, setRetention] = useState('30');
  const [dbUrl, setDbUrl] = useState('postgresql://admin:password@localhost:5432/hse_logs');
  
  const [saveStatus, setSaveStatus] = useState('');

  const handleSave = (e) => {
    e.preventDefault();
    setSaveStatus('Saving configuration to edge node...');
    setTimeout(() => setSaveStatus('Configuration synced successfully.'), 1000);
    setTimeout(() => setSaveStatus(''), 4000);
  };

  return (
    <div className="max-w-5xl space-y-6">
      
      <div className="flex justify-between items-end mb-6">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Sliders size={20} className="text-blue-400" /> System Configuration
          </h1>
          <p className="text-xs text-slate-400 mt-1">Manage edge node parameters and AI detection thresholds.</p>
        </div>
        <button 
          onClick={handleSave}
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-md text-sm font-bold flex items-center gap-2 transition-colors"
        >
          <Save size={16} /> Sync Configuration
        </button>
      </div>

      {saveStatus && (
        <div className="bg-emerald-950/50 border border-emerald-500/50 text-emerald-400 text-xs font-mono p-3 rounded-lg flex items-center gap-2">
          <Server size={14} /> {saveStatus}
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl space-y-6">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3">
            <Shield size={16} className="text-emerald-400" /> Vision Model Parameters
          </h2>
          
          <div>
            <div className="flex justify-between items-center mb-2">
              <label className="text-xs font-semibold text-slate-400 uppercase">Detection Confidence Threshold</label>
              <span className="text-xs bg-slate-950 px-2 py-1 rounded border border-slate-700 font-mono text-blue-400">
                {(confidence * 100).toFixed(0)}%
              </span>
            </div>
            <input 
              type="range" 
              min="0.1" 
              max="0.95" 
              step="0.05" 
              value={confidence}
              onChange={(e) => setConfidence(parseFloat(e.target.value))}
              className="w-full accent-blue-500"
            />
            <p className="text-[11px] text-slate-500 mt-2">Higher thresholds reduce false positives but may miss partial violations.</p>
          </div>

          <div className="space-y-3 pt-2">
            <label className="text-xs font-semibold text-slate-400 uppercase block">Active Tracking Classes</label>
            {Object.entries(activeClasses).map(([key, isActive]) => (
              <div key={key} className="flex justify-between items-center bg-slate-950 p-3 rounded-lg border border-slate-800">
                <span className="text-sm font-semibold text-slate-300 capitalize">NO-{key}</span>
                <button 
                  onClick={() => setActiveClasses(prev => ({ ...prev, [key]: !isActive }))}
                  className={`w-10 h-5 rounded-full relative transition-colors ${isActive ? 'bg-blue-600' : 'bg-slate-700'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${isActive ? 'translate-x-5' : ''}`}></span>
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <div className="flex justify-between items-center border-b border-slate-800 pb-3 mb-4">
              <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                <Camera size={16} className="text-amber-400" /> Edge Stream Registry
              </h2>
              <button className="text-[11px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded flex items-center gap-1 transition">
                <Plus size={12} /> Add Feed
              </button>
            </div>
            
            <div className="space-y-2">
              {cameras.map((cam, idx) => (
                <div key={idx} className="flex justify-between items-center bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <div>
                    <p className="text-xs font-bold text-slate-200">{cam.label}</p>
                    <p className="text-[10px] font-mono text-slate-500">{cam.id}</p>
                  </div>
                  <button className="text-slate-500 hover:text-red-400 transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 border-b border-slate-800 pb-3 mb-4">
              <Database size={16} className="text-purple-400" /> Data Integration
            </h2>
            
            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase block mb-1">Local Log Retention</label>
                <select 
                  value={retention}
                  onChange={(e) => setRetention(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-md focus:ring-blue-500 focus:border-blue-500 p-2"
                >
                  <option value="7">7 Days (Auto-Purge)</option>
                  <option value="14">14 Days (Auto-Purge)</option>
                  <option value="30">30 Days (Standard)</option>
                  <option value="90">90 Days (Archive)</option>
                </select>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase block mb-1">Central DB Sync String (Optional)</label>
                <input 
                  type="text" 
                  value={dbUrl}
                  onChange={(e) => setDbUrl(e.target.value)}
                  placeholder="postgresql://..."
                  className="w-full bg-slate-950 border border-slate-700 text-slate-500 text-xs font-mono rounded-md focus:ring-blue-500 focus:border-blue-500 p-2"
                />
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}