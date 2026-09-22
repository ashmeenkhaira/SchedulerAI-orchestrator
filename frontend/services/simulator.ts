import { API_BASE_URL, WEBSOCKET_URL } from '../constants';
import { AgentInfo, ComparisonResponse, MetricsPayload } from '../types';

export interface StartRunResult {
  status: string;
  run_id: number;
  strategy: string;
}

/**
 * The free Render tier suspends the backend after inactivity, and waking it
 * takes ~20-30s. Without this the first visitor gets a dashboard of zeros and
 * a dead WebSocket, which looks like a broken deployment rather than a
 * sleeping one. Poll until it answers so the UI can say what is happening.
 */
export const waitForBackend = async (
  onAttempt?: (attempt: number, elapsedMs: number) => void,
  timeoutMs = 90_000
): Promise<boolean> => {
  const startedAt = Date.now();
  for (let attempt = 1; Date.now() - startedAt < timeoutMs; attempt++) {
    onAttempt?.(attempt, Date.now() - startedAt);
    try {
      const response = await fetch(`${API_BASE_URL}/`, { cache: 'no-store' });
      if (response.ok) return true;
    } catch {
      // Still asleep or unreachable — fall through and retry.
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  return false;
};

export const fetchAgentInfo = async (): Promise<AgentInfo> => {
  const response = await fetch(`${API_BASE_URL}/api/agent/info`);
  if (!response.ok) throw new Error(`Failed to read agent info: ${response.statusText}`);
  return await response.json();
};

/**
 * Defaults here, not the backend's, govern every run started from the UI —
 * App.tsx calls this with the strategy only.
 */
export const startSimulation = async (
  strategy: string,
  sim_steps: number = 2000,
  arrival_prob: number = 0.6,
  mean_service: number = 8.0,
  seed: number = 1
): Promise<StartRunResult> => {
  const response = await fetch(`${API_BASE_URL}/api/runs/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ strategy, sim_steps, arrival_prob, mean_service, seed }),
  });
  if (!response.ok) throw new Error(`Failed to start simulation: ${response.statusText}`);
  return await response.json();
};

export const stopSimulation = async (runId: number) => {
  const response = await fetch(`${API_BASE_URL}/api/runs/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: runId }),
  });
  if (!response.ok) throw new Error(`Failed to stop simulation: ${response.statusText}`);
  return await response.json();
};

export const clearDecisions = async (runId: number) => {
  const response = await fetch(`${API_BASE_URL}/api/runs/${runId}/decisions`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error(`Failed to clear decisions: ${response.statusText}`);
  return await response.json();
};

/**
 * Auto-reconnecting metrics socket.
 *
 * The previous version opened one socket and gave up if it failed. On a cold
 * backend the very first connection always fails, so the dashboard stayed
 * empty for the whole visit even after the server came up. Returns a closer
 * that also suppresses the reconnect, so React strict-mode remounts and real
 * unmounts both stop cleanly.
 */
export const connectWebSocket = (
  onMessage: (data: { run_id: number; payload: MetricsPayload }) => void,
  onStatus?: (connected: boolean) => void
): { close: () => void } => {
  let socket: WebSocket | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  const open = () => {
    if (closed) return;
    socket = new WebSocket(WEBSOCKET_URL);

    socket.onopen = () => onStatus?.(true);

    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch (e) {
        console.error('WebSocket parse error', e);
      }
    };

    socket.onclose = () => {
      onStatus?.(false);
      if (closed) return;
      retryTimer = setTimeout(open, 3_000);
    };

    // onerror is always followed by onclose, so reconnection is handled there.
    socket.onerror = () => socket?.close();
  };

  open();

  return {
    close: () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    },
  };
};

/**
 * Only base_strategy + replay_run_id are sent. The backend looks the run up
 * and uses ITS stored seed/load/step-count for both arms, so the replayed
 * decisions are applied to the trajectory that actually produced them.
 */
export const runComparison = async (
  base_strategy: string,
  replayRunId: number | null,
  treatment: 'replay' | 'heuristic' = 'replay'
): Promise<ComparisonResponse> => {
  const response = await fetch(`${API_BASE_URL}/api/runs/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ base_strategy, replay_run_id: replayRunId, treatment }),
  });
  if (!response.ok) throw new Error(`Failed to run comparison: ${response.statusText}`);
  return await response.json();
};
