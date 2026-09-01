// Target path in your project: src/services/geminiService.ts

import { MetricsPayload, AgentDecision } from '../types';
import { API_BASE_URL } from '../constants';

export const askGemini = async (
  metrics: MetricsPayload,
  runId: number | null
): Promise<AgentDecision> => {
  // The Gemini call itself now happens server-side (see
  // app/gemini_service.py) so the API key never reaches the browser.
  // The backend also handles the rate-limit retry-once-then-degrade
  // behavior that used to live here.
  let decision: AgentDecision;
  try {
    const res = await fetch(`${API_BASE_URL}/api/agent/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...metrics, run_id: runId }),
    });
    if (!res.ok) throw new Error(`agent/decide failed: ${res.status} ${res.statusText}`);
    decision = await res.json();
  } catch (error) {
    console.error("Gemini Agent Error:", error);
    return { action: "explain", strategy: null, params: {}, message: "Agent connection interrupted. Decision making offline." };
  }

  // Only actuate if we have an active run and AI wants to switch
  if (runId !== null && decision.action === "switch_strategy" && decision.strategy) {
    // Wrapped in try/catch: previously an unhandled rejection here propagated
    // up into App.tsx's queryAgent(), skipping setIsThinking(false) and
    // permanently freezing the agent loop after a single network blip.
    // A failure to actuate/log should degrade gracefully, not kill the loop.
    try {
      // 1. Actually switch the running engine's strategy
      const switchRes = await fetch(`${API_BASE_URL}/api/runs/switch-strategy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, strategy: decision.strategy })
      });
      if (!switchRes.ok) {
        console.error(`switch-strategy failed: ${switchRes.status} ${switchRes.statusText}`);
      }

      // 2. Log the decision for replay in comparison mode
      const logRes = await fetch(`${API_BASE_URL}/api/runs/log-decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, step: metrics.time, strategy: decision.strategy })
      });
      if (!logRes.ok) {
        console.error(`log-decision failed: ${logRes.status} ${logRes.statusText}`);
      }
    } catch (postError) {
      console.error("Failed to actuate/log Gemini decision:", postError);
    }
  }

  return decision;
};
