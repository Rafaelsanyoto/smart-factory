import { useState, useEffect, useRef } from 'react';
import { Camera, ShieldAlert, CheckCircle, XCircle, MapPin, AlertTriangle, Video } from 'lucide-react';

const CAMERA_REGISTRY = [
  { id: 'stream_01', label: 'Assembly Line A (Cam 01)' },
  { id: 'stream_02', label: 'Welding Bay B (Cam 02)' }
];

export default function LiveMonitor({ pendingIncidents = [], setPendingIncidents, verifiedIncidents = [], setVerifiedIncidents }) {  const [activeStream, setActiveStream] = useState('stream_01');
  const activeViolationsRef = useRef({}); 
  const trackLastSeenRef = useRef({});   
  
  const [detections, setDetections] = useState([]);

useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(`http://127.0.0.1:8000/api/data/${activeStream}`);
        const data = await response.json();
        
        // Log the raw data to verify the FastAPI payload
        console.log("Raw API Payload:", data);

        if (data.status === "success" && Array.isArray(data.detections)) {
          
          // Safely normalize JSON keys (handles class, name, or class_name)
          const parsedDetections = data.detections.map(d => ({
            ...d,
            label: (d.class_name || d.name || d.class || "").toUpperCase()
          }));

          const newDetections = parsedDetections.filter(d => d.label !== 'PERSON');
          setDetections(newDetections);

          const currentViolations = newDetections.filter(d => d.label.includes("NO-"));
          const nowTime = new Date().toLocaleTimeString();
          const nowMs = Date.now();
          const newIncidentsToAdd = [];

          currentViolations.forEach(v => {
            const trackId = v.track_id !== null && v.track_id !== undefined ? v.track_id : 'untracked';
            
            // FIX: Using a pipe delimiter prevents splitting errors on 'stream_01'
            const violationKey = `${activeStream}|${trackId}|${v.label}`;
            
            trackLastSeenRef.current[trackId] = nowMs;

            if (!activeViolationsRef.current[violationKey]) {
              activeViolationsRef.current[violationKey] = true;
              
              const activeCam = CAMERA_REGISTRY.find(cam => cam.id === activeStream);
              const zoneName = activeCam ? activeCam.label : activeStream;

              newIncidentsToAdd.push({
                id: nowMs + Math.random(),
                time: nowTime,
                type: v.label,
                zone: zoneName,
                status: "PENDING"
              });
            }
          });

          Object.keys(activeViolationsRef.current).forEach(key => {
            const parts = key.split('|');
            const tId = parts[1]; 
            const lastSeen = trackLastSeenRef.current[tId] || 0;
            if (nowMs - lastSeen > 3000) {
              delete activeViolationsRef.current[key]; 
            }
          });

          if (newIncidentsToAdd.length > 0) {
            if (typeof setPendingIncidents === 'function') {
              setPendingIncidents(prev => [...newIncidentsToAdd, ...prev].slice(0, 10));
            } else {
              console.error("CRITICAL: setPendingIncidents prop is missing. Check App.jsx routing.");
            }
          }
        }
      } catch (error) {
        // Expose silent failures
        console.error("API Polling Error:", error);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [activeStream, setPendingIncidents]);

  const handleVerifyIncident = (id, status) => {
    const target = pendingIncidents.find(inc => inc.id === id);
    if (!target) return;

    setPendingIncidents(prev => prev.filter(inc => inc.id !== id));
    if (status === 'CONFIRMED') {
      setVerifiedIncidents(prev => [{ ...target, status: 'CONFIRMED' }, ...prev]);
    }
  };

  return (
    <div className="grid grid-cols-3 gap-6">
      <div className="col-span-2 space-y-6">
        
        <div className="flex items-center gap-4 bg-slate-900/50 p-2 rounded-lg border border-slate-800/50 w-fit">
          <label htmlFor="camera-select" className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Select Feed:
          </label>
          <div className="relative">
            <select
              id="camera-select"
              value={activeStream}
              onChange={(e) => setActiveStream(e.target.value)}
              className="appearance-none bg-slate-950 border border-slate-700 text-slate-200 text-sm font-semibold rounded-md focus:ring-blue-500 focus:border-blue-500 block w-64 p-2 pl-9 cursor-pointer hover:border-slate-500 transition-colors"
            >
              {CAMERA_REGISTRY.map((cam) => (
                <option key={cam.id} value={cam.id}>
                  {cam.label}
                </option>
              ))}
            </select>
            <Video size={16} className="absolute left-2.5 top-2.5 text-blue-500 pointer-events-none" />
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 shadow-2xl relative">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-sm font-semibold flex items-center gap-2 text-slate-200">
              <Camera size={18} className="text-blue-400"/> Active Feed // {activeStream.toUpperCase()}
            </h2>
          </div>
          
          <div className="bg-slate-950 h-[480px] rounded-lg border border-slate-800 flex items-center justify-center relative overflow-hidden shadow-inner">
            <img 
              key={activeStream}
              src={`http://127.0.0.1:8000/api/video/${activeStream}`} 
              alt="CCTV Stream" 
              className="w-full h-full object-cover"
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Pending Review</p>
            <p className="text-3xl font-mono font-bold mt-1 text-amber-400">{pendingIncidents.length}</p>
          </div>
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Active Violations</p>
            <p className="text-3xl font-mono font-bold mt-1 text-blue-400">{detections.length}</p>
          </div>
          <div className="bg-slate-900 p-4 rounded-xl border border-slate-800">
            <p className="text-xs text-slate-400 uppercase">Safety Status</p>
            <p className={`text-xl font-mono font-bold mt-2 ${detections.length > 0 ? "text-red-500 animate-pulse" : "text-emerald-400"}`}>
              {detections.length > 0 ? "VIOLATION DETECTED" : "SECURE"}
            </p>
          </div>
        </div>
      </div>

      <div className="col-span-1 space-y-6">
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-sm font-semibold flex items-center gap-2 text-amber-400"><AlertTriangle size={16}/> Incident Verification Queue</h2>
            <span className="text-xs bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded-full font-mono font-bold">{pendingIncidents.length} New</span>
          </div>
          <div className="space-y-3 max-h-[320px] overflow-y-auto pr-1">
            {pendingIncidents.length === 0 ? (
              <div className="bg-slate-950 p-6 rounded-lg text-center border border-slate-800 text-slate-500 text-xs">No pending incidents requiring review.</div>
            ) : (
              pendingIncidents.map((incident) => (
                <div key={incident.id} className="bg-slate-950 border border-amber-500/30 p-3.5 rounded-lg space-y-2.5">
                  <div className="flex justify-between items-center text-xs"><span className="font-mono text-slate-400">{incident.time}</span><span className="font-bold text-red-400 bg-red-950/50 px-2 py-0.5 rounded border border-red-800/40">{incident.type}</span></div>
                  <div className="flex justify-between items-center pt-1">
                    <span className="text-[11px] text-slate-300 flex items-center gap-1"><MapPin size={12}/> {incident.zone}</span>
                    <div className="flex gap-2">
                      <button onClick={() => handleVerifyIncident(incident.id, 'DISMISSED')} className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs flex items-center gap-1"><XCircle size={14}/> Dismiss</button>
                      <button onClick={() => handleVerifyIncident(incident.id, 'CONFIRMED')} className="px-2.5 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-xs flex items-center gap-1 font-semibold"><CheckCircle size={14}/> Confirm</button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 shadow-xl">
          <h2 className="text-sm font-semibold flex items-center gap-2 mb-3 text-red-400"><ShieldAlert size={16}/> Confirmed Incident Registry</h2>
          <div className="space-y-2.5 max-h-[220px] overflow-y-auto pr-1">
            {verifiedIncidents.map((log, index) => (
              <div key={index} className="bg-slate-950 border border-slate-800 p-3 rounded-lg flex justify-between items-center text-xs">
                <div><span className="font-bold text-red-400 block">{log.type}</span><span className="text-slate-500 font-mono text-[10px]">{log.time}</span></div>
                <span className="text-slate-300 bg-slate-900 px-2 py-1 rounded border border-slate-800 text-[11px]">{log.zone}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}