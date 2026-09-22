import { API_BASE_URL, WEBSOCKET_URL } from '../constants';
import { ComparisonResponse, MetricsPayload } from '../types';

export interface StartRunResult {
  status: string;
  run_id: number;
  strategy: string;
}

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

export const connectWebSocket = (
  onMessage: (data: { run_id: number; payload: MetricsPayload }) => void
): WebSocket => {
  const ws = new WebSocket(WEBSOCKET_URL);

  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch (e) {
      console.error('WebSocket parse error', e);
    }
  };

  ws.onerror = (e) => console.error('WebSocket error', e);

  return ws;
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
