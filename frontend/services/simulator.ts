import { API_BASE_URL, WEBSOCKET_URL } from '../constants';
import { MetricsPayload } from '../types';

export const startSimulation = async (
  strategy: string,
  sim_steps: number = 2000,
  arrival_prob: number = 0.5,
  mean_service: number = 5.0,
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

export const runComparison = async (
  base_strategy: string,
  steps: number = 200,
  arrival_prob: number = 0.4,
  mean_service: number = 5.0,
  seed: number = 42
) => {
  const response = await fetch(`${API_BASE_URL}/api/runs/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      base_strategy,
      steps,
      arrival_prob,
      mean_service,
      seed
    })
  });
  if (!response.ok) throw new Error(`Failed to run comparison: ${response.statusText}`);
  return await response.json();
};
