import React, { useEffect, useRef } from 'react';
import { AgentDecision } from '../types';
import { Bot, Terminal } from 'lucide-react';

interface AgentLogsProps {
  logs: { decision: AgentDecision, timestamp: number }[];
}

export const AgentLogs: React.FC<AgentLogsProps> = ({ logs }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="bg-slate-900 border-l border-slate-800 w-full lg:w-96 flex flex-col h-full">
      <div className="p-4 border-b border-slate-800 flex items-center gap-2 bg-slate-900 sticky top-0 z-10">
        <Bot className="w-5 h-5 text-indigo-400" />
        <h2 className="font-semibold text-white">Agent Decisions</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 font-mono text-sm">
        {logs.length === 0 && (
          <div className="text-slate-500 text-center mt-10 flex flex-col items-center">
            <Terminal className="w-8 h-8 mb-2 opacity-50" />
            <p>Waiting for analysis...</p>
          </div>
        )}
        
        {logs.map((log, idx) => (
          <div 
            key={idx} 
            className={`
              p-3 rounded border
              ${log.decision.action === 'switch_strategy' ? 'bg-indigo-950/40 border-indigo-500/50' : 
                log.decision.action === 'start_run' ? 'bg-emerald-950/40 border-emerald-500/50' :
                'bg-slate-800/50 border-slate-700'}
            `}
          >
            <div className="flex justify-between items-center mb-2 text-xs text-slate-400">
              <span>{new Date(log.timestamp).toLocaleTimeString()}</span>
              <span className="uppercase font-bold tracking-wider">{log.decision.action}</span>
            </div>
            
            <p className="text-slate-200 mb-2">{log.decision.message}</p>
            
            {log.decision.strategy && (
              <div className="text-xs bg-slate-950 inline-block px-2 py-1 rounded text-indigo-300 border border-indigo-500/30">
                Strategy: {log.decision.strategy}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
