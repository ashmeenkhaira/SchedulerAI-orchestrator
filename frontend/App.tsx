// Target path in your project: src/App.tsx

import React, { useState, useEffect, useRef } from 'react';
import { startSimulation, stopSimulation, connectWebSocket, runComparison } from './services/simulator';
import { askGemini } from './services/geminiService';
import { MetricsCharts } from './components/MetricsCharts';
import { ServerGrid } from './components/ServerGrid';
import { AgentLogs } from './components/AgentLogs';
import { ComparisonCharts } from './components/ComparisonCharts';
import { MetricsPayload, AgentDecision, ComparisonMetrics } from './types';
import { Play, Square, Cpu, Activity, GitCompare } from 'lucide-react';
import { API_BASE_URL } from './constants';

// Phase 6: full shape of the /runs/compare response, including the new
// meta/diagnostics fields. ComparisonMetrics (from ./types) still covers
// just the chart-data shape consumed by <ComparisonCharts />.
interface ComparisonResponse {
  comparison: ComparisonMetrics;
  summary: {
    baseline_strategy: string;
    steps: number;
    baseline_final_queue: number;
    gemini_final_queue: number;
    baseline_total_completed: number;
    gemini_total_completed: number;
  };
  meta: {
    used_replay: boolean;
    source_run_id: number | null;
    seed: number;
    steps: number;
    decisions_replayed: number;
  };
  diagnostics: {
    steps_gemini_matched_base_strategy: number;
    steps_gemini_used_other_strategy: number;
  };
}

const App: React.FC = () => {
  const [metrics, setMetrics] = useState<MetricsPayload | null>(null);
  const [history, setHistory] = useState<MetricsPayload[]>([]);
  const [logs, setLogs] = useState<{ decision: AgentDecision, timestamp: number }[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  // Tracks the most recent run we know exists in the DB — set as soon as a
  // run starts, and (unlike `runId`) deliberately NOT cleared when the run
  // stops. Comparison only needs the DB-persisted seed/load/decision-log
  // for this run, none of which depend on it still being live, so gating
  // comparison on `runId !== null` (live only) was unnecessarily strict —
  // it blocked the natural workflow of letting a run play out, accumulate
  // several real Gemini decisions, stop it, and compare afterward.
  const [lastRunId, setLastRunId] = useState<number | null>(null);

  // Comparison mode state
  const [comparisonResult, setComparisonResult] = useState<ComparisonResponse | null>(null);
  const [isComparing, setIsComparing] = useState(false);
  const [comparisonLoading, setComparisonLoading] = useState(false);

  // Controls whether we should listen to the WebSocket
  const isRunningRef = useRef(false);
  // Throttle: track when we last called Gemini (ms timestamp)
  const lastGeminiCallRef = useRef<number>(0);
  const GEMINI_THROTTLE_MS = 15_000; // max 1 call per 15s (stays under 5/min free tier)

  const strategies = ['baseline', 'random_backoff', 'consistent_hash', 'token_ring', 'leader_election'];

  // WebSocket Connection
  useEffect(() => {
    const ws = connectWebSocket((data) => {
      // STRICT FILTER: Only update UI if we believe we are running
      if (!isRunningRef.current) return;

      setMetrics(data.payload);
      setRunId(data.run_id);
      setHistory(prev => {
        const newHistory = [...prev, data.payload];
        return newHistory.length > 50 ? newHistory.slice(1) : newHistory;
      });
    });

    return () => ws.close();
  }, []);

  // Gemini Agent Loop — throttled to at most once per GEMINI_THROTTLE_MS
  useEffect(() => {
    if (!metrics || isThinking || !isRunningRef.current || !isRunning) return;

    const now = Date.now();
    if (now - lastGeminiCallRef.current < GEMINI_THROTTLE_MS) return;

    const queryAgent = async () => {
      lastGeminiCallRef.current = Date.now();
      setIsThinking(true);
      const decision = await askGemini(metrics, runId);
      setLogs(prev => [...prev, { decision, timestamp: Date.now() }]);
      setIsThinking(false);
    };

    queryAgent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metrics]);

  const handleStart = async (strategy: string) => {
    try {
      // 1. Allow updates
      isRunningRef.current = true;
      setIsRunning(true);

      // 2. Start Backend
      const result = await startSimulation(strategy);
      if (result.run_id) {
        await fetch(`${API_BASE_URL}/api/runs/${result.run_id}/decisions`, { method: "DELETE" });
        setLastRunId(result.run_id);
      }

      // Starting a fresh run invalidates any comparison that was anchored
      // to a previous run's decision log.
      setComparisonResult(null);
      setIsComparing(false);
    } catch (e) {
      console.error(e);
      alert('Failed to start run');
      isRunningRef.current = false;
      setIsRunning(false);
    }
  };

  const handleStop = async () => {
    if (runId !== null) {
      try {
        // 1. Block all future updates IMMEDIATELY
        isRunningRef.current = false;
        setIsRunning(false);

        // 2. Tell backend to stop
        await stopSimulation(runId);

        // 3. Clear UI
        setRunId(null);
        setMetrics(null);

      } catch (e) {
        console.error("Stop failed:", e);
        setIsRunning(false);
      }
    }
  };

  const handleRunComparison = async (strategy: string) => {
    // Comparison only needs a run that EXISTS in the DB with a config and
    // (ideally) a decision log — it doesn't need to still be live. Using
    // lastRunId lets you stop a run and still compare against it.
    if (lastRunId === null) return;

    setComparisonLoading(true);
    setIsComparing(true);
    try {
      const result: ComparisonResponse = await runComparison(strategy, lastRunId);
      setComparisonResult(result);
    } catch (e) {
      console.error("Comparison failed:", e);
      alert('Failed to run comparison');
    } finally {
      setComparisonLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-200 overflow-hidden font-sans">
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Header */}
        <header className="h-16 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-600 rounded-lg">
              <Cpu className="w-6 h-6 text-white" />
            </div>
            <h1 className="font-bold text-xl tracking-tight text-white">SchedulerAI Orchestrator</h1>
          </div>

          <div className="flex items-center gap-4">
            {isThinking && (
              <div className="flex items-center gap-2 text-indigo-400 text-sm animate-pulse">
                <Activity className="w-4 h-4" /> Agent Analyzing...
              </div>
            )}
            <div className="h-6 w-px bg-slate-700"></div>
            <button
              onClick={handleStop}
              disabled={runId === null}
              className={`flex items-center gap-2 px-4 py-2 rounded-md font-medium transition-colors ${runId !== null ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30' : 'bg-slate-800 text-slate-500 cursor-not-allowed'}`}
            >
              <Square className="w-4 h-4 fill-current" /> Stop Run
            </button>
          </div>
        </header>

        {/* Dashboard Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-slate-800 p-4 rounded-xl border border-slate-700">
              <div className="text-slate-400 text-xs font-mono mb-1">RUN ID</div>
              <div className="text-2xl font-bold text-white">{runId ?? 'IDLE'}</div>
            </div>
            <div className="bg-slate-800 p-4 rounded-xl border border-slate-700">
              <div className="text-slate-400 text-xs font-mono mb-1">QUEUE LEN</div>
              <div className={`text-2xl font-bold ${metrics && metrics.queue_len > 40 ? 'text-red-400' : 'text-white'}`}>
                {metrics?.queue_len ?? '--'}
              </div>
            </div>
            <div className="bg-slate-800 p-4 rounded-xl border border-slate-700">
              <div className="text-slate-400 text-xs font-mono mb-1">COMPLETED</div>
              <div className="text-2xl font-bold text-emerald-400">{metrics?.completed_total ?? '--'}</div>
            </div>
            <div className="bg-slate-800 p-4 rounded-xl border border-slate-700">
              <div className="text-slate-400 text-xs font-mono mb-1">TIME STEP</div>
              <div className="text-2xl font-bold text-indigo-400">{metrics?.time ?? '--'}</div>
            </div>
          </div>

          <MetricsCharts history={history} currentMetrics={metrics} />

          {metrics && <ServerGrid servers={metrics.servers} />}

          <div className="mt-8 bg-slate-800 p-6 rounded-xl border border-slate-700">
            <h3 className="text-white font-medium mb-4 flex items-center gap-2">
              <Play className="w-4 h-4 text-emerald-400" /> Start Simulation
            </h3>
            <div className="flex flex-wrap gap-3">
              {strategies.map(s => (
                <button
                  key={s}
                  onClick={() => handleStart(s)}
                  className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium rounded transition-colors border border-slate-600"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Comparison Mode Section */}
          <div className="mt-6 bg-gradient-to-r from-indigo-900/30 to-purple-900/30 p-6 rounded-xl border border-indigo-500/30">
            <h3 className="text-white font-medium mb-2 flex items-center gap-2">
              <GitCompare className="w-4 h-4 text-indigo-400" /> Compare: With vs Without Gemini AI
            </h3>
            <p className="text-slate-400 text-sm mb-4">
              Run identical simulations comparing fixed strategy (no AI) vs dynamic AI-guided strategy switching.
            </p>

            {lastRunId === null && (
              <p className="text-amber-400 text-xs mb-3 font-mono">
                ⚠ Start (and optionally stop) a run first — comparison replays that run's real Gemini decisions under its actual seed/load.
              </p>
            )}

            <div className="flex flex-wrap gap-3">
              {strategies.map(s => (
                <button
                  key={`compare-${s}`}
                  onClick={() => handleRunComparison(s)}
                  disabled={comparisonLoading || lastRunId === null}
                  title={lastRunId === null ? "Start a run first" : undefined}
                  className={`px-4 py-2 text-sm font-medium rounded transition-colors border ${(comparisonLoading || lastRunId === null)
                    ? 'bg-slate-700 text-slate-500 cursor-not-allowed border-slate-600'
                    : 'bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border-indigo-500/50'
                    }`}
                >
                  {comparisonLoading ? 'Running...' : `Compare vs ${s}`}
                </button>
              ))}
            </div>

            {/* Phase 6: surface whether this was a real replay or the
                heuristic fallback — never let the two look the same. */}
            {comparisonResult?.meta && (
              <div
                className={`mt-4 px-3 py-2 rounded text-xs font-mono border ${comparisonResult.meta.used_replay
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                  }`}
              >
                {comparisonResult.meta.used_replay
                  ? `✓ Replaying ${comparisonResult.meta.decisions_replayed} real Gemini decisions from run #${comparisonResult.meta.source_run_id} — seed ${comparisonResult.meta.seed}, ${comparisonResult.meta.steps} steps`
                  : '⚠ No logged Gemini decisions found for this run — showing a heuristic stand-in, NOT real Gemini output'}
              </div>
            )}

            {comparisonResult?.diagnostics && comparisonResult.summary && (
              <div className="mt-2 text-xs text-slate-400 font-mono">
                AI arm matched the base strategy for {comparisonResult.diagnostics.steps_gemini_matched_base_strategy} / {comparisonResult.summary.steps} steps
                ({comparisonResult.diagnostics.steps_gemini_used_other_strategy} steps used a different strategy)
              </div>
            )}

            {isComparing && (
              <button
                onClick={() => { setIsComparing(false); setComparisonResult(null); }}
                className="mt-4 px-3 py-1 text-xs text-slate-400 hover:text-white border border-slate-600 rounded"
              >
                Clear Comparison
              </button>
            )}
          </div>

          {/* Comparison Charts */}
          <ComparisonCharts comparisonData={comparisonResult?.comparison ?? null} isComparing={isComparing} />
        </div>
      </div>

      {/* Sidebar */}
      <AgentLogs logs={logs} />
    </div>
  );
};

export default App;