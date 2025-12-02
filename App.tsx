import React, { useState, useEffect, useRef } from 'react';
import { startSimulation, stopSimulation, connectWebSocket } from './services/simulator';
import { askGemini } from './services/geminiService';
import { MetricsCharts } from './components/MetricsCharts';
import { ServerGrid } from './components/ServerGrid';
import { AgentLogs } from './components/AgentLogs';
import { MetricsPayload, AgentDecision } from './types';
import { Play, Square, Cpu, Activity } from 'lucide-react';

const App: React.FC = () => {
  const [metrics, setMetrics] = useState<MetricsPayload | null>(null);
  const [history, setHistory] = useState<MetricsPayload[]>([]);
  const [logs, setLogs] = useState<{ decision: AgentDecision, timestamp: number }[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  
  // Controls whether we should listen to the WebSocket
  const isRunningRef = useRef(false);
  
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

  // Gemini Agent Loop
  useEffect(() => {
    if (!metrics || isThinking || !isRunningRef.current) return;

    const queryAgent = async () => {
      setIsThinking(true);
      const decision = await askGemini(metrics);
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
      
      // 2. Start Backend
      await startSimulation(strategy);
    } catch (e) {
      console.error(e);
      alert('Failed to start run');
      isRunningRef.current = false;
    }
  };

  const handleStop = async () => {
    if (runId !== null) {
      try {
        // 1. Block all future updates IMMEDIATELY
        isRunningRef.current = false;

        // 2. Tell backend to stop
        await stopSimulation(runId);
        
        // 3. Clear UI
        setRunId(null);
        setMetrics(null);
        
      } catch (e) {
        console.error("Stop failed:", e);
      }
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
        </div>
      </div>

      {/* Sidebar */}
      <AgentLogs logs={logs} />
    </div>
  );
};

export default App;