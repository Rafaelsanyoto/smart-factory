import { useState } from 'react';
import { BarChart3, AlertTriangle, Crosshair, CheckCircle2, Video } from 'lucide-react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer 
} from 'recharts';

const CAMERA_REGISTRY = [
  { id: 'stream_01', label: 'Assembly Line A (Cam 01)' },
  { id: 'stream_02', label: 'Welding Bay B (Cam 02)' }
];

export default function Analytics({ verifiedIncidents = [] }) {
  const [selectedZone, setSelectedZone] = useState('ALL');

  const availableZones = CAMERA_REGISTRY.map(cam => cam.label);

  const totalIncidents = verifiedIncidents.length;

  const typeCounts = verifiedIncidents.reduce((acc, curr) => {
    acc[curr.type] = (acc[curr.type] || 0) + 1;
    return acc;
  }, {});
  const primaryViolation = Object.entries(typeCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || 'N/A';

  const zoneCounts = verifiedIncidents.reduce((acc, curr) => {
    acc[curr.zone] = (acc[curr.zone] || 0) + 1;
    return acc;
  }, {});
  const highestRiskZone = Object.entries(zoneCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || 'N/A';

  const filteredIncidents = selectedZone === 'ALL' 
    ? verifiedIncidents 
    : verifiedIncidents.filter(inc => inc.zone === selectedZone);

  const chartData = Object.values(filteredIncidents.reduce((acc, inc) => {
    const timeParts = inc.time.split(':');
    const timeMin = `${timeParts[0]}:${timeParts[1]}`; 
    
    if (!acc[timeMin]) {
      acc[timeMin] = { time: timeMin, 'NO-HARDHAT': 0, 'NO-SAFETY VEST': 0, 'NO-MASK': 0 };
    }
    acc[timeMin][inc.type] = (acc[timeMin][inc.type] || 0) + 1;
    return acc;
  }, {})).sort((a, b) => a.time.localeCompare(b.time));

  return (
    <div className="space-y-6">
      
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 shadow-lg">
          <div className="flex justify-between items-start mb-2">
            <p className="text-xs text-slate-400 uppercase font-semibold">Total Verified</p>
            <BarChart3 size={16} className="text-blue-400" />
          </div>
          <p className="text-3xl font-mono font-bold text-slate-100">{totalIncidents}</p>
          <p className="text-xs text-emerald-400 mt-2 font-medium">Current Session</p>
        </div>

        <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 shadow-lg">
          <div className="flex justify-between items-start mb-2">
            <p className="text-xs text-slate-400 uppercase font-semibold">Highest Risk Zone</p>
            <AlertTriangle size={16} className="text-amber-400" />
          </div>
          <p className="text-lg font-bold text-slate-100 truncate mt-1">{highestRiskZone}</p>
        </div>

        <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 shadow-lg">
          <div className="flex justify-between items-start mb-2">
            <p className="text-xs text-slate-400 uppercase font-semibold">Primary Violation</p>
            <Crosshair size={16} className="text-red-400" />
          </div>
          <p className="text-lg font-bold text-red-400 mt-1">{primaryViolation}</p>
        </div>

        <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 shadow-lg">
          <div className="flex justify-between items-start mb-2">
            <p className="text-xs text-slate-400 uppercase font-semibold">System Status</p>
            <CheckCircle2 size={16} className="text-emerald-400" />
          </div>
          <p className="text-xl font-bold text-slate-100 mt-1">Live Tracking</p>
        </div>
      </div>

      <div className="bg-slate-900 rounded-xl p-5 border border-slate-800 shadow-xl">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <BarChart3 size={18} className="text-blue-400"/> Live Session Violation Frequency
          </h2>
          
          <div className="flex items-center gap-3 bg-slate-950 p-1.5 rounded-lg border border-slate-800">
             <Video size={14} className="text-slate-400 ml-2" />
             <select
                value={selectedZone}
                onChange={(e) => setSelectedZone(e.target.value)}
                className="bg-transparent text-slate-200 text-xs font-semibold focus:outline-none cursor-pointer pr-2"
              >
                <option value="ALL">All Cameras (Global)</option>
                {availableZones.map(zone => (
                  <option key={zone} value={zone}>{zone}</option>
                ))}
              </select>
          </div>
        </div>
        
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis 
                dataKey="time" 
                stroke="#64748b" 
                tick={{fill: '#64748b', fontSize: 12}} 
                tickLine={false}
                axisLine={false}
              />
              <YAxis 
                stroke="#64748b" 
                tick={{fill: '#64748b', fontSize: 12}} 
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <Tooltip 
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '8px' }}
                itemStyle={{ fontSize: '12px', fontWeight: 'bold' }}
                labelStyle={{ color: '#94a3b8', marginBottom: '4px' }}
              />
              <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
              
              <Line type="monotone" name="No Safety Vest" dataKey="NO-SAFETY VEST" stroke="#f87171" strokeWidth={3} dot={{r: 4, fill: '#f87171'}} activeDot={{r: 6}} />
              <Line type="monotone" name="No Hardhat" dataKey="NO-HARDHAT" stroke="#fbbf24" strokeWidth={3} dot={{r: 4, fill: '#fbbf24'}} activeDot={{r: 6}} />
              <Line type="monotone" name="No Mask" dataKey="NO-MASK" stroke="#60a5fa" strokeWidth={3} dot={{r: 4, fill: '#60a5fa'}} activeDot={{r: 6}} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

    </div>
  );
}