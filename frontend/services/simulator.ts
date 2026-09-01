// Target path in your project: src/services/simulator.ts

import { API_BASE_URL, WEBSOCKET_URL } from '../constants';
import { MetricsPayload } from '../types';

export const startSimulation = async (
  strategy: string,
  sim_steps: number = 2000,
  arrival_prob: number = 0.6,  // high load: ~0.85 jobs/step vs ~1.0 capacity → queue builds
  mean_service: number = 8.0,   // longer jobs → servers stay busy longer
  seed: number = 1
) => {
  const response = await fetch(`${API_BASE_URL}/api/runs/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      strategy,
      sim_steps,
      arrival_prob,
      mean_service,
      seed
    })
  });
  if (!response.ok) throw new Error(`Failed to start simulation: ${response.statusText}`);
  return await response.json();
};

export const stopSimulation = async (runId: number) => {
  const response = await fetch(`${API_BASE_URL}/api/runs/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: runId })
  });
  if (!response.ok) throw new Error(`Failed to stop simulation: ${response.statusText}`);
  return await response.json();
};

export const connectWebSocket = (
  onMessage: (data: { run_id: number, payload: MetricsPayload }) => void
): WebSocket => {
  const ws = new WebSocket(WEBSOCKET_URL);

  ws.onopen = () => console.log('WebSocket connected');

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch (e) {
      console.error('WebSocket parse error', e);
    }
  };

  ws.onerror = (e) => console.error('WebSocket error', e);
  ws.onclose = () => console.log('WebSocket closed');

  return ws;
};

/**
 * Phase 6: only base_strategy + replayRunId are sent now.
 *
 * Previously this sent hardcoded steps/arrival_prob/mean_service/seed
 * (200, 0.85, 8.0, 42) that didn't match the live run's actual config
 * (sim_steps=2000, seed=1 by default) — meaning the AI arm's replayed
 * decisions were being applied to a completely different randomized
 * trajectory than the one that produced them.
 *
 * The backend now looks up replay_run_id in the DB and uses THAT run's
 * real seed/load/step-count for both comparison arms (see Phase 3 in
 * api.py). Sending those values from the frontend would just be ignored
 * whenever replayRunId is provided, so we no longer pretend to control
 * them here.
 */
export const runComparison = async (base_strategy: string, replayRunId: number | null) => {
  const response = await fetch(`${API_BASE_URL}/api/runs/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      base_strategy,
      replay_run_id: replayRunId
    })
  });
  if (!response.ok) throw new Error(`Failed to run comparison: ${response.statusText}`);
  return await response.json();
};