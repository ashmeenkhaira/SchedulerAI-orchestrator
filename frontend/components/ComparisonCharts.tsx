import React from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts';
import { ComparisonMetrics } from '../types';

interface ComparisonChartsProps {
  comparisonData: ComparisonMetrics | null;
  isComparing: boolean;
}

export const ComparisonCharts: React.FC<ComparisonChartsProps> = ({ comparisonData, isComparing }) => {
  if (!comparisonData || !isComparing) return null;

  const chartConfig = {
    withGemini: { stroke: '#22c55e', name: 'With Gemini AI' },
    withoutGemini: { stroke: '#ef4444', name: 'Without Gemini AI' }
  };

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload || !payload.length) return null;
    return (
      <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-lg">
        <p className="text-slate-300 text-xs mb-2">Time: {label}</p>
        {payload.map((entry: any, index: number) => (
          <p key={index} style={{ color: entry.stroke }} className="text-sm">
            {entry.name}: {entry.value?.toFixed(2) ?? '--'}
          </p>
        ))}
      </div>
    );
  };

  return (
    <div className="mt-6 p-6 bg-slate-800/50 rounded-xl border border-indigo-500/30">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-2 h-2 bg-indigo-500 rounded-full animate-pulse"></div>
        <h2 className="text-lg font-bold text-white">Gemini AI Comparison Analysis</h2>
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Queue Length Comparison */}
        <div className="bg-slate-900 p-4 rounded-xl border border-slate-700">
          <h3 className="text-sm font-medium text-slate-400 mb-4">Queue Length</h3>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={comparisonData.queueLength.slice(-50)}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="time" stroke="#94a3b8" fontSize={10} />
                <YAxis stroke="#94a3b8" fontSize={10} />
                <Tooltip content={<CustomTooltip />} />
                <Legend 
                  wrapperStyle={{ fontSize: '10px' }}
                  iconSize={8}
                />
                <Line
                  type="monotone"
                  dataKey="withGemini"
                  stroke={chartConfig.withGemini.stroke}
                  name={chartConfig.withGemini.name}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="withoutGemini"
                  stroke={chartConfig.withoutGemini.stroke}
                  name={chartConfig.withoutGemini.name}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Completed Jobs Comparison */}
        <div className="bg-slate-900 p-4 rounded-xl border border-slate-700">
          <h3 className="text-sm font-medium text-slate-400 mb-4">Jobs Completed</h3>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={comparisonData.completedTotal.slice(-50)}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="time" stroke="#94a3b8" fontSize={10} />
                <YAxis stroke="#94a3b8" fontSize={10} />
                <Tooltip content={<CustomTooltip />} />
                <Legend 
                  wrapperStyle={{ fontSize: '10px' }}
                  iconSize={8}
                />
                <Line
                  type="monotone"
                  dataKey="withGemini"
                  stroke={chartConfig.withGemini.stroke}
                  name={chartConfig.withGemini.name}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="withoutGemini"
                  stroke={chartConfig.withoutGemini.stroke}
                  name={chartConfig.withoutGemini.name}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Fairness Comparison */}
        <div className="bg-slate-900 p-4 rounded-xl border border-slate-700">
          <h3 className="text-sm font-medium text-slate-400 mb-4">Fairness (Lower is Better)</h3>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={comparisonData.fairnessStd.slice(-50)}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="time" stroke="#94a3b8" fontSize={10} />
                <YAxis stroke="#94a3b8" fontSize={10} />
                <Tooltip content={<CustomTooltip />} />
                <Legend 
                  wrapperStyle={{ fontSize: '10px' }}
                  iconSize={8}
                />
                <Line
                  type="monotone"
                  dataKey="withGemini"
                  stroke={chartConfig.withGemini.stroke}
                  name={chartConfig.withGemini.name}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="withoutGemini"
                  stroke={chartConfig.withoutGemini.stroke}
                  name={chartConfig.withoutGemini.name}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-900 p-4 rounded-lg border border-green-500/30">
          <div className="text-xs text-slate-400 mb-1">With Gemini - Avg Queue</div>
          <div className="text-xl font-bold text-green-400">
            {comparisonData.queueLength.length > 0
              ? (comparisonData.queueLength.reduce((a, b) => a + b.withGemini, 0) / comparisonData.queueLength.length).toFixed(1)
              : '--'}
          </div>
        </div>
        <div className="bg-slate-900 p-4 rounded-lg border border-red-500/30">
          <div className="text-xs text-slate-400 mb-1">Without Gemini - Avg Queue</div>
          <div className="text-xl font-bold text-red-400">
            {comparisonData.queueLength.length > 0
              ? (comparisonData.queueLength.reduce((a, b) => a + b.withoutGemini, 0) / comparisonData.queueLength.length).toFixed(1)
              : '--'}
          </div>
        </div>
        <div className="bg-slate-900 p-4 rounded-lg border border-green-500/30">
          <div className="text-xs text-slate-400 mb-1">With Gemini - Total Jobs</div>
          <div className="text-xl font-bold text-green-400">
            {comparisonData.completedTotal.length > 0
              ? comparisonData.completedTotal[comparisonData.completedTotal.length - 1]?.withGemini ?? '--'
              : '--'}
          </div>
        </div>
        <div className="bg-slate-900 p-4 rounded-lg border border-red-500/30">
          <div className="text-xs text-slate-400 mb-1">Without Gemini - Total Jobs</div>
          <div className="text-xl font-bold text-red-400">
            {comparisonData.completedTotal.length > 0
              ? comparisonData.completedTotal[comparisonData.completedTotal.length - 1]?.withoutGemini ?? '--'
              : '--'}
          </div>
        </div>
      </div>
    </div>
  );
};
