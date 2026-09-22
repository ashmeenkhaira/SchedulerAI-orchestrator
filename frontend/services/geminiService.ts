import { MetricsPayload, AgentDecision } from '../types';
import { API_BASE_URL } from '../constants';

const OFFLINE: AgentDecision = {
  action: 'explain',
  strategy: null,
  params: {},
  message: 'Agent connection interrupted. Decision making offline.',
  degraded: true,
};

/**
 * Ask the backend agent proxy what to do, then actuate and log the result.
 *
 * The model call happens server-side (app/agent_service.py), so the API key
 * never reaches the browser and the provider — Ollama, Gemini or the
 * deterministic mock — is chosen by backend config, not by this file.
 */
export const askGemini = async (
  metrics: MetricsPayload,
  runId: number | null
): Promise<AgentDecision> => {
  let decision: AgentDecision;
  try {
    const res = await fetch(`${API_BASE_URL}/api/agent/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...metrics, run_id: runId }),
    });
    if (!res.ok) throw new Error(`agent/decide failed: ${res.status} ${res.statusText}`);
    decision = await res.json();
  } catch (error) {
    console.error('Gemini Agent Error:', error);
    return OFFLINE;
  }

  if (runId === null) return decision;

  // Wrapped so a network blip degrades gracefully instead of rejecting into
  // App.tsx's queryAgent(), which used to skip setIsThinking(false) and
  // permanently freeze the agent loop.
  try {
    if (decision.action === 'switch_strategy' && decision.strategy) {
      const switchRes = await fetch(`${API_BASE_URL}/api/runs/switch-strategy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId, strategy: decision.strategy }),
      });
      if (!switchRes.ok) {
        console.error(`switch-strategy failed: ${switchRes.status} ${switchRes.statusText}`);
      }
    }

    // Log every REAL decision, including "explain" holds, with the model's
    // reasoning attached.
    //
    // Degraded responses are skipped. They are not agent output - they are the
    // proxy telling us it never reached the model - and writing them to the
    // decision log made a run with zero model contact look like a run where
    // the agent deliberately held its strategy.
    if (decision.degraded) return decision;

    const logRes = await fetch(`${API_BASE_URL}/api/runs/log-decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        run_id: runId,
        step: metrics.time,
        strategy: decision.strategy,
        action: decision.action,
        raw_message: decision.message,
      }),
    });
    if (!logRes.ok) {
      console.error(`log-decision failed: ${logRes.status} ${logRes.statusText}`);
    }
  } catch (postError) {
    console.error('Failed to actuate/log agent decision:', postError);
  }

  return decision;
};
