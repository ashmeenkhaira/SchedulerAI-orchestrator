import React from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { ComparisonDataPoint, ComparisonMetrics } from '../types';

interface ComparisonChartsProps {
  comparisonData: ComparisonMetrics | null;
  isComparing: boolean;
}

const SERIES = {
  withGemini: { stroke: '#22c55e', name: 'Agent-guided' },
  withoutGemini: { stroke: '#ef4444', name: 'Fixed strategy' },
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-lg">
      <p className="text-slate-300 text-xs mb-2">Step {label}</p>
      {payload.map((entry: any) => (
        <p key={entry.name} style={{ color: entry.stroke }} className="text-sm">
          {entry.name}: {entry.value?.toFixed(2) ?? '--'}
        </p>
      ))}
    </div>
  );
};

/**
 * Plots the full series, not a trailing window. These are completed runs, so
 * slicing to the last 50 steps hid most of the data — and the summary tiles
 * that used to sit below averaged the FULL arrays, so the numbers and the
 * curves silently described different spans. Aggregates now live in one place,
 * the summary table in App.tsx.
 */
const ComparisonChart: React.FC<{ title: string; data: ComparisonDataPoint[] }> = ({ title, data }) => (
  <div className="bg-slate-900 p-4 rounded-xl border border-slate-700">
    <h3 className="text-sm font-medium text-slate-400 mb-4">{title}</h3>
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="time" stroke="#94a3b8" fontSize={10} />
          <YAxis stroke="#94a3b8" fontSize={10} />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: '10px' }} iconSize={8} />
          {(Object.keys(SERIES) as (keyof typeof SERIES)[]).map((key) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={SERIES[key].stroke}
              name={SERIES[key].name}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  </div>
);

export const ComparisonCharts: React.FC<ComparisonChartsProps> = ({ comparisonData, isComparing }) => {
  if (!comparisonData || !isComparing) return null;

  return (
    <div className="mt-6 p-6 bg-slate-800/50 rounded-xl border border-indigo-500/30">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-2 h-2 bg-indigo-500 rounded-full animate-pulse" />
        <h2 className="text-lg font-bold text-white">Comparison Analysis</h2>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <ComparisonChart title="Queue Length (lower is better)" data={comparisonData.queueLength} />
        <ComparisonChart title="Jobs Completed (higher is better)" data={comparisonData.completedTotal} />
        <ComparisonChart title="Fairness Std (lower is better)" data={comparisonData.fairnessStd} />
      </div>
    </div>
  );
};
