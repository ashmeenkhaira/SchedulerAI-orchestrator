import React, { useState, useEffect, useRef } from 'react';
import {
  clearDecisions,
  connectWebSocket,
  fetchAgentInfo,
  runComparison,
  startSimulation,
  stopSimulation,
  waitForBackend,
} from './services/simulator';
import { askGemini } from './services/geminiService';
import { MetricsCharts } from './components/MetricsCharts';
import { ServerGrid } from './components/ServerGrid';
import { AgentLogs } from './components/AgentLogs';
import { ComparisonCharts } from './components/ComparisonCharts';
import {
  AgentDecision,
  AgentInfo,
  ComparisonResponse,
  MetricsPayload,
  STRATEGIES,
} from './types';
import { Play, Square, Cpu, Activity, GitCompare, Loader2, WifiOff, Bot } from 'lucide-react';

const AGENT_THROTTLE_MS = 15_000; // stays under the 5 req/min free tier
const HISTORY_LIMIT = 50;

// The strategy a visitor's auto-started run begins on. random_backoff is the
// most visibly dynamic of the five, so the dashboard has something moving
// within a second or two of the page settling.
const DEMO_STRATEGY = 'random_backoff';

type BootState = 'waking' | 'ready' | 'unreachable';

const App: React.FC = () => {
  const [metrics, setMetrics] = useState<MetricsPayload | null>(null);
  const [history, setHistory] = useState<MetricsPayload[]>([]);
  const [logs, setLogs] = useState<{ decision: AgentDecision; timestamp: number }[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isThinking, setIsThinking] = useState(false);

  // Survives a stop, unlike runId, so you can let a run play out, stop it, and
  // still compare against its persisted config and decision log.
  const [lastRunId, setLastRunId] = useState<number | null>(null);

  const [comparison, setComparison] = useState<ComparisonResponse | null>(null);
  const [isComparing, setIsComparing] = useState(false);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  // 'replay' uses the run's real logged agent decisions. 'heuristic' runs the
  // rule table instead — useful as an ablation, but it is never substituted
  // automatically, because its output is not agent output.
  const [treatment, setTreatment] = useState<'replay' | 'heuristic'>('replay');

  const [boot, setBoot] = useState<BootState>('waking');
  const [bootElapsed, setBootElapsed] = useState(0);
  const [socketUp, setSocketUp] = useState(false);
  const [agentInfo, setAgentInfo] = useState<AgentInfo | null>(null);

  const isRunningRef = useRef(false);
  const lastAgentCallRef = useRef<number>(0);
  const bootedRef = useRef(false);

  useEffect(() => {
    const ws = connectWebSocket(
      (data) => {
        if (!isRunningRef.current) return;
        setMetrics(data.payload);
        setRunId(data.run_id);
        setHistory((prev) => {
          const next = [...prev, data.payload];
          return next.length > HISTORY_LIMIT ? next.slice(next.length - HISTORY_LIMIT) : next;
        });
      },
      setSocketUp
    );
    return () => ws.close();
  }, []);

  // Boot sequence. A visitor should land on a dashboard that is already
  // running: the free Render tier sleeps, so the first load has to wait out a
  // ~20-30s cold start, and an empty page with five buttons reads as broken
  // rather than idle. Wait for the backend, report what the agent is, then
  // start a run without anyone having to click.
  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;

    let cancelled = false;

    (async () => {
      const awake = await waitForBackend((_attempt, elapsedMs) => {
        if (!cancelled) setBootElapsed(Math.round(elapsedMs / 1000));
      });
      if (cancelled) return;

      if (!awake) {
        setBoot('unreachable');
        return;
      }

      try {
        setAgentInfo(await fetchAgentInfo());
      } catch {
        // Label is a nicety; a missing one must not block the demo.
      }

      setBoot('ready');
      if (!cancelled) await handleStart(DEMO_STRATEGY);
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Agent loop, throttled to at most one call per GEMINI_THROTTLE_MS.
  useEffect(() => {
    if (!metrics || isThinking || !isRunningRef.current || !isRunning) return;
    if (Date.now() - lastAgentCallRef.current < AGENT_THROTTLE_MS) return;

    const queryAgent = async () => {
      lastAgentCallRef.current = Date.now();
      setIsThinking(true);
      try {
        const decision = await askGemini(metrics, runId);
        setLogs((prev) => [...prev, { decision, timestamp: Date.now() }]);
      } finally {
        setIsThinking(false);
      }
    };

    queryAgent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metrics]);

  const handleStart = async (strategy: string) => {
    try {
      isRunningRef.current = true;
      setIsRunning(true);
      setHistory([]);
      setLogs([]);

      const result = await startSimulation(strategy);

      // Set runId from the start response rather than waiting for the first
      // WebSocket frame. Previously runId was populated ONLY by an inbound
      // message, and the Stop button is gated on it — so if the socket was
      // slow or never connected, the run could not be stopped from the UI at
      // all, and the engine kept running server-side.
      setRunId(result.run_id);
      setLastRunId(result.run_id);
      await clearDecisions(result.run_id);

      setComparison(null);
      setIsComparing(false);
    } catch (e) {
      // No alert(): this also runs unattended on page load, and a modal is a
      // hostile way to greet a visitor. The banner carries the failure.
      console.error('Failed to start run:', e);
      setBoot('unreachable');
      isRunningRef.current = false;
      setIsRunning(false);
      setRunId(null);
    }
  };

  const handleStop = async () => {
    if (runId === null) return;
    isRunningRef.current = false;
    setIsRunning(false);
    try {
      await stopSimulation(runId);
    } catch (e) {
      console.error('Stop failed:', e);
    } finally {
      setRunId(null);
      setMetrics(null);
    }
  };

  const handleRunComparison = async (strategy: string) => {
    if (lastRunId === null) return;
    setComparisonLoading(true);
    setIsComparing(true);
    try {
      setComparison(await runComparison(strategy, lastRunId, treatment));
    } catch (e) {
      console.error('Comparison failed:', e);
      alert('Failed to run comparison');
    } finally {
      setComparisonLoading(false);
    }
  };

  const tiles: [string, string | number, string][] = [
    ['RUN ID', runId ?? 'IDLE', 'text-white'],
    ['QUEUE LEN', metrics?.queue_len ?? '--',
      metrics && metrics.queue_len > 40 ? 'text-red-400' : 'text-white'],
    ['COMPLETED', metrics?.completed_total ?? '--', 'text-emerald-400'],
    ['AVG WAIT', metrics?.avg_wait ?? '--', 'text-amber-400'],
    ['TIME STEP', metrics?.time ?? '--', 'text-indigo-400'],
  ];

  return (
    <div className="flex h-screen bg-slate-950 text-slate-200 overflow-hidden font-sans">
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        <header className="h-16 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-600 rounded-lg">
              <Cpu className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="font-bold text-xl tracking-tight text-white leading-none">Nova</h1>
              <p className="text-[11px] text-slate-400 font-mono mt-0.5">
                8-node distributed scheduler simulator
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {agentInfo && (
              <div
                className={`hidden sm:flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono border ${
                  agentInfo.is_live_model
                    ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                    : 'bg-slate-800 text-slate-400 border-slate-700'
                }`}
                title={
                  agentInfo.is_live_model
                    ? `Live model decisions via ${agentInfo.provider}`
                    : 'Demo mode: deterministic rule table, no API key required. Set AGENT_PROVIDER=ollama for live model decisions.'
                }
              >
                <Bot className="w-3.5 h-3.5" />
                {agentInfo.is_live_model ? agentInfo.model : 'demo: rule-based agent'}
              </div>
            )}
            {!socketUp && boot === 'ready' && (
              <div className="flex items-center gap-2 text-amber-400 text-xs font-mono">
                <WifiOff className="w-3.5 h-3.5" /> reconnecting
              </div>
            )}
            {isThinking && (
              <div className="flex items-center gap-2 text-indigo-400 text-sm animate-pulse">
                <Activity className="w-4 h-4" /> Agent Analyzing...
              </div>
            )}
            <div className="h-6 w-px bg-slate-700" />
            <button
              onClick={handleStop}
              disabled={runId === null}
              className={`flex items-center gap-2 px-4 py-2 rounded-md font-medium transition-colors ${
                runId !== null
                  ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                  : 'bg-slate-800 text-slate-500 cursor-not-allowed'
              }`}
            >
              <Square className="w-4 h-4 fill-current" /> Stop Run
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-6">
          {boot === 'waking' && (
            <div className="mb-6 bg-slate-800/70 border border-slate-700 rounded-xl p-5 flex items-start gap-4">
              <Loader2 className="w-5 h-5 text-indigo-400 animate-spin shrink-0 mt-0.5" />
              <div>
                <p className="text-white font-medium">Waking the backend…</p>
                <p className="text-slate-400 text-sm mt-1">
                  This deployment runs on Render's free tier, which suspends the service
                  after inactivity. A cold start takes roughly 20–30 seconds
                  {bootElapsed > 0 && ` (${bootElapsed}s elapsed)`}. A simulation starts
                  automatically as soon as it answers — nothing to click.
                </p>
              </div>
            </div>
          )}

          {boot === 'unreachable' && (
            <div className="mb-6 bg-red-500/10 border border-red-500/30 rounded-xl p-5">
              <p className="text-red-300 font-medium">Backend unreachable</p>
              <p className="text-slate-400 text-sm mt-1">
                The free-tier service did not wake within 90 seconds. Reload to retry, or
                run it locally — see the README. The measured results in{' '}
                <code className="text-slate-300">results/</code> are committed to the repo
                and do not depend on this deployment being up.
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
            {tiles.map(([label, value, colour]) => (
              <div key={label} className="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <div className="text-slate-400 text-xs font-mono mb-1">{label}</div>
                <div className={`text-2xl font-bold ${colour}`}>{value}</div>
              </div>
            ))}
          </div>

          <MetricsCharts history={history} currentMetrics={metrics} />

          {metrics && <ServerGrid servers={metrics.servers} />}

          <div className="mt-8 bg-slate-800 p-6 rounded-xl border border-slate-700">
            <h3 className="text-white font-medium mb-1 flex items-center gap-2">
              <Play className="w-4 h-4 text-emerald-400" /> Restart with a different strategy
            </h3>
            <p className="text-slate-400 text-sm mb-4">
              A run starts automatically on load. Each strategy is a different rule for
              deciding which of the 8 servers claims the next job; the agent may switch
              between them while the run is live.
            </p>
            <div className="flex flex-wrap gap-3">
              {STRATEGIES.map((s) => (
                <button
                  key={s}
                  onClick={() => handleStart(s)}
                  disabled={isRunning}
                  className={`px-4 py-2 text-sm font-medium rounded transition-colors border ${
                    isRunning
                      ? 'bg-slate-800 text-slate-500 cursor-not-allowed border-slate-700'
                      : 'bg-slate-700 hover:bg-slate-600 text-slate-200 border-slate-600'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
            {isRunning && (
              <p className="text-slate-400 text-xs mt-3 font-mono">
                Stop the current run before starting another.
              </p>
            )}
          </div>

          <div className="mt-6 bg-gradient-to-r from-indigo-900/30 to-purple-900/30 p-6 rounded-xl border border-indigo-500/30">
            <h3 className="text-white font-medium mb-2 flex items-center gap-2">
              <GitCompare className="w-4 h-4 text-indigo-400" /> Compare: agent-guided vs fixed strategy
            </h3>
            <p className="text-slate-400 text-sm mb-4">
              Both arms replay the same seed under Common Random Numbers, so the only
              variable is the scheduling decisions.
            </p>

            {lastRunId === null && (
              <p className="text-amber-400 text-xs mb-3 font-mono">
                Start a run first — comparison replays that run's decisions under its actual seed and load.
              </p>
            )}

            <div className="flex items-center gap-2 mb-4 text-xs font-mono">
              <span className="text-slate-400">Treatment arm:</span>
              {(['replay', 'heuristic'] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setTreatment(mode)}
                  className={`px-2 py-1 rounded border transition-colors ${
                    treatment === mode
                      ? 'bg-indigo-600/40 text-indigo-200 border-indigo-400/60'
                      : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-slate-200'
                  }`}
                >
                  {mode === 'replay' ? 'real agent decisions' : 'rule table (ablation)'}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap gap-3">
              {STRATEGIES.map((s) => (
                <button
                  key={`compare-${s}`}
                  onClick={() => handleRunComparison(s)}
                  disabled={comparisonLoading || lastRunId === null}
                  className={`px-4 py-2 text-sm font-medium rounded transition-colors border ${
                    comparisonLoading || lastRunId === null
                      ? 'bg-slate-700 text-slate-500 cursor-not-allowed border-slate-600'
                      : 'bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border-indigo-500/50'
                  }`}
                >
                  {comparisonLoading ? 'Running...' : `Compare vs ${s}`}
                </button>
              ))}
            </div>

            {comparison && (
              <>
                <TreatmentBanner comparison={comparison} />

                {!comparison.meta.crn_verified && (
                  <div className="mt-2 px-3 py-2 rounded text-xs font-mono border bg-red-500/10 text-red-400 border-red-500/30">
                    CRN check FAILED — the two arms did not see identical arrivals and failures.
                    These numbers are not a controlled comparison.
                  </div>
                )}

                {comparison.diagnostics.steps_gemini_used_other_strategy > 0 && (
                  <div className="mt-2 text-xs text-slate-400 font-mono">
                    Treatment arm diverged from {comparison.summary.baseline_strategy} for{' '}
                    {comparison.diagnostics.steps_gemini_used_other_strategy} / {comparison.summary.steps} steps
                    {comparison.diagnostics.strategies_used_by_treatment.length > 0 &&
                      ` — used: ${comparison.diagnostics.strategies_used_by_treatment.join(', ')}`}
                  </div>
                )}

                <ComparisonSummary comparison={comparison} />
              </>
            )}

            {isComparing && (
              <button
                onClick={() => {
                  setIsComparing(false);
                  setComparison(null);
                }}
                className="mt-4 px-3 py-1 text-xs text-slate-400 hover:text-white border border-slate-600 rounded"
              >
                Clear Comparison
              </button>
            )}
          </div>

          <ComparisonCharts comparisonData={comparison?.comparison ?? null} isComparing={isComparing} />
        </div>
      </div>

      <AgentLogs logs={logs} />
    </div>
  );
};

/**
 * Says exactly what the "Agent" column contains. Four outcomes, never conflated:
 * a real replay, an agent that held, no agent data at all, or the rule table.
 */
const TreatmentBanner: React.FC<{ comparison: ComparisonResponse }> = ({ comparison }) => {
  const { treatment_mode, decisions_replayed, decisions_logged, source_run_id, seed, steps } =
    comparison.meta;

  const banner: Record<typeof treatment_mode, { tone: string; text: string }> = {
    replay: {
      tone: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
      text: `Replaying ${decisions_replayed} real agent decisions from run #${source_run_id} — seed ${seed}, ${steps} steps`,
    },
    agent_held: {
      tone: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
      text: `The agent ran (${decisions_logged} decisions) but never switched strategy, so both arms are identical and every delta is zero. That is the result, not a missing comparison.`,
    },
    no_agent_data: {
      tone: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
      text: 'This run has no agent decisions — the model was never reached. Nothing to replay, so both arms are identical. Set GEMINI_API_KEY and run again, or switch the treatment arm to the rule table.',
    },
    heuristic: {
      tone: 'bg-purple-500/10 text-purple-300 border-purple-500/30',
      text: 'Treatment arm is the rule table (gemini_strategy_selector), NOT the model. Useful as an ablation — this is the "does the LLM beat an if/else chain?" baseline.',
    },
  };

  const { tone, text } = banner[treatment_mode];
  return <div className={`mt-4 px-3 py-2 rounded text-xs font-mono border ${tone}`}>{text}</div>;
};

/** Aggregate metrics for both arms. Lower is better for every row except throughput. */
const ComparisonSummary: React.FC<{ comparison: ComparisonResponse }> = ({ comparison }) => {
  const { control, treatment } = comparison.summary;
  const rows: [string, number, number, boolean][] = [
    ['Avg queue length', control.avg_queue_len, treatment.avg_queue_len, true],
    ['Avg wait (steps)', control.avg_wait, treatment.avg_wait, true],
    ['Avg turnaround (steps)', control.avg_turnaround, treatment.avg_turnaround, true],
    ['Throughput (jobs/step)', control.throughput, treatment.throughput, false],
    ['Jobs completed', control.jobs_completed, treatment.jobs_completed, false],
    ['Avg fairness std', control.avg_fairness_std, treatment.avg_fairness_std, true],
  ];

  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-slate-400 border-b border-slate-700">
            <th className="text-left py-2 pr-4">Metric</th>
            <th className="text-right py-2 px-3">Fixed</th>
            <th className="text-right py-2 px-3">Agent</th>
            <th className="text-right py-2 pl-3">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, ctrl, treat, lowerIsBetter]) => {
            const pct = ctrl === 0 ? null : ((treat - ctrl) / ctrl) * 100;
            const improved = lowerIsBetter ? treat < ctrl : treat > ctrl;
            return (
              <tr key={label} className="border-b border-slate-800">
                <td className="py-2 pr-4 text-slate-300">{label}</td>
                <td className="text-right py-2 px-3 text-slate-400">{ctrl}</td>
                <td className="text-right py-2 px-3 text-slate-200">{treat}</td>
                <td
                  className={`text-right py-2 pl-3 ${
                    pct === null || treat === ctrl
                      ? 'text-slate-500'
                      : improved
                      ? 'text-emerald-400'
                      : 'text-red-400'
                  }`}
                >
                  {pct === null ? '—' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default App;
