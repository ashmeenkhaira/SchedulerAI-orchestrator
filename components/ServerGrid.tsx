import React from 'react';
import { ServerStatus } from '../types';
import { Server, Zap } from 'lucide-react';

interface ServerGridProps {
  servers: ServerStatus[];
}

export const ServerGrid: React.FC<ServerGridProps> = ({ servers }) => {
  return (
    <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 shadow-md">
      <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <Server className="w-5 h-5 text-indigo-400" /> Server Cluster
      </h3>
      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-8 gap-4">
        {servers.map((server) => (
          <div
            key={server.sid}
            className={`
              relative p-3 rounded-lg border flex flex-col items-center justify-center transition-all duration-300
              ${server.busy 
                ? 'bg-red-900/20 border-red-500/50 shadow-[0_0_10px_rgba(239,68,68,0.2)]' 
                : 'bg-emerald-900/20 border-emerald-500/50 shadow-[0_0_10px_rgba(16,185,129,0.2)]'}
            `}
          >
            <div className={`
              absolute top-2 right-2 w-2 h-2 rounded-full 
              ${server.busy ? 'bg-red-500 animate-pulse' : 'bg-emerald-500'}
            `} />
            
            <div className="mb-2">
              <Zap className={`w-6 h-6 ${server.busy ? 'text-red-400' : 'text-emerald-400'}`} />
            </div>
            
            <div className="text-sm font-mono font-bold text-slate-200">S{server.sid}</div>
            <div className="text-xs text-slate-400 mt-1">
              Done: <span className="text-white font-medium">{server.completed}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
