import React from 'react';
import { ServerStatus } from '../types';
import { Server, Zap, AlertTriangle } from 'lucide-react';

interface ServerGridProps {
  servers: ServerStatus[];
}

/**
 * Three states, not two. `failed` is present in the metrics payload and is
 * what the agent reasons about via num_failed, but the grid used to render
 * only busy/idle — so an offline server looked exactly like a free one.
 */
const styleFor = (server: ServerStatus) => {
  if (server.failed) {
    return {
      container: 'bg-amber-900/20 border-amber-500/60',
      dot: 'bg-amber-500 animate-pulse',
      icon: 'text-amber-400',
      label: 'FAILED',
    };
  }
  if (server.busy) {
    return {
      container: 'bg-red-900/20 border-red-500/50',
      dot: 'bg-red-500 animate-pulse',
      icon: 'text-red-400',
      label: 'BUSY',
    };
  }
  return {
    container: 'bg-emerald-900/20 border-emerald-500/50',
    dot: 'bg-emerald-500',
    icon: 'text-emerald-400',
    label: 'IDLE',
  };
};

export const ServerGrid: React.FC<ServerGridProps> = ({ servers }) => {
  const failedCount = servers.filter((s) => s.failed).length;

  return (
    <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 shadow-md">
      <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <Server className="w-5 h-5 text-indigo-400" /> Server Cluster
        {failedCount > 0 && (
          <span className="ml-2 text-xs font-mono text-amber-400 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> {failedCount} offline
          </span>
        )}
      </h3>
      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-8 gap-4">
        {servers.map((server) => {
          const style = styleFor(server);
          return (
            <div
              key={server.sid}
              className={`relative p-3 rounded-lg border flex flex-col items-center justify-center transition-all duration-300 ${style.container}`}
            >
              <div className={`absolute top-2 right-2 w-2 h-2 rounded-full ${style.dot}`} />

              <div className="mb-2">
                <Zap className={`w-6 h-6 ${style.icon}`} />
              </div>

              <div className="text-sm font-mono font-bold text-slate-200">S{server.sid}</div>
              <div className="text-[10px] font-mono text-slate-500 mt-0.5">{style.label}</div>
              <div className="text-xs text-slate-400 mt-1">
                Done: <span className="text-white font-medium">{server.completed}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
