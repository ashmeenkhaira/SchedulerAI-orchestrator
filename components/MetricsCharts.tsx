import React from 'react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';
import { MetricsPayload } from '../types';

interface MetricsChartsProps {
  history: MetricsPayload[];
  currentMetrics: MetricsPayload | null;
}

export const MetricsCharts: React.FC<MetricsChartsProps> = ({ history, currentMetrics }) => {
  const chartData = history.slice(-50); // Keep last 50 points for readability
  
  const serverData = currentMetrics 
    ? currentMetrics.servers.map(s => ({ name: `S${s.sid}`, completed: s.completed }))
    : [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <div className="bg-slate-800 p-4 rounded-xl border border-slate-700 shadow-md">
        <h3 className="text-sm font-medium text-slate-400 mb-4">Queue Length (Real-time)</h3>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" hide />
              <YAxis stroke="#94a3b8" />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1e293b', borderColor: '#475569', color: '#f8fafc' }}
                itemStyle={{ color: '#f8fafc' }}
              />
              <Line 
                type="monotone" 
                dataKey="queue_len" 
                stroke="#f59e0b" 
                strokeWidth={2} 
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-slate-800 p-4 rounded-xl border border-slate-700 shadow-md">
        <h3 className="text-sm font-medium text-slate-400 mb-4">Jobs Completed per Server</h3>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={serverData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis dataKey="name" stroke="#94a3b8" fontSize={10} />
              <YAxis stroke="#94a3b8" />
              <Tooltip 
                cursor={{ fill: '#334155', opacity: 0.2 }}
                contentStyle={{ backgroundColor: '#1e293b', borderColor: '#475569', color: '#f8fafc' }}
              />
              <Bar dataKey="completed" fill="#6366f1" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                {serverData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={index % 2 === 0 ? '#818cf8' : '#6366f1'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};
