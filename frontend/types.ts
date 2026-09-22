export interface ServerStatus {
  sid: number;
  busy: boolean;
  completed: number;
  failed: boolean;
}

export interface MetricsPayload {
  time: number;
  queue_len: number;
  completed_total: number;
  fairness_std: number;
  queue_rate: number;
  num_failed: number;
  /** Mean steps a job spent queued before being picked up. */
  avg_wait: number;
  deadlock_detected: boolean;
  servers: ServerStatus[];
  run_id?: number;
  strategy?: string;
}

/** Valid strategy names — single source of truth on the frontend. */
export type StrategyName =
  | 'baseline'
  | 'random_backoff'
  | 'consistent_hash'
  | 'token_ring'
  | 'leader_election';

export const STRATEGIES: StrategyName[] = [
  'baseline',
  'random_backoff',
  'consistent_hash',
  'token_ring',
  'leader_election',
];

export interface AgentDecision {
  action: 'switch_strategy' | 'explain';
  strategy: StrategyName | null;
  params: Record<string, unknown>;
  message: string;
  /** True when the proxy never reached the model. Not agent output; never logged. */
  degraded?: boolean;
}

// --- Comparison ---

export interface ComparisonDataPoint {
  time: number;
  withGemini: number;
  withoutGemini: number;
}

export interface ComparisonMetrics {
  queueLength: ComparisonDataPoint[];
  completedTotal: ComparisonDataPoint[];
  fairnessStd: ComparisonDataPoint[];
}

/** One arm's aggregate metrics, as produced by summarise() in api.py. */
export interface ArmSummary {
  avg_queue_len: number;
  max_queue_len: number;
  avg_wait: number;
  avg_turnaround: number;
  throughput: number;
  jobs_arrived: number;
  jobs_completed: number;
  final_queue_len: number;
  final_fairness_std: number;
  avg_fairness_std: number;
  starvation_steps: number;
}

export interface ComparisonResponse {
  comparison: ComparisonMetrics;
  summary: {
    baseline_strategy: string;
    steps: number;
    control: ArmSummary;
    treatment: ArmSummary;
    delta_pct: {
      avg_queue_len: number | null;
      avg_wait: number | null;
      throughput: number | null;
      avg_fairness_std: number | null;
    };
  };
  meta: {
    /**
     * replay        - replaying real logged agent switches
     * agent_held    - agent ran but never switched; both arms identical
     * no_agent_data - no agent decisions exist for this run
     * heuristic     - rule table, explicitly requested, NOT the model
     */
    treatment_mode: 'replay' | 'agent_held' | 'no_agent_data' | 'heuristic';
    used_replay: boolean;
    source_run_id: number | null;
    seed: number;
    steps: number;
    arrival_prob: number;
    mean_service: number;
    decisions_logged: number;
    decisions_replayed: number;
    /** False means the two arms did not see the same workload — results are not controlled. */
    crn_verified: boolean;
  };
  diagnostics: {
    steps_gemini_matched_base_strategy: number;
    steps_gemini_used_other_strategy: number;
    strategies_used_by_treatment: string[];
  };
}
