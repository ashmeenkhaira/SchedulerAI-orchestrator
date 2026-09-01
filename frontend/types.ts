// Target path in your project: src/types.ts

export interface ServerStatus {
  sid: number;
  busy: boolean;
  completed: number;
  failed?: boolean;
}

export interface MetricsPayload {
  time: number;
  queue_len: number;
  completed_total: number;
  fairness_std: number;
  // Made non-optional: both fields are always present in get_metrics()
  // output from the backend. Keeping them optional here meant every
  // consumer had to null-check before using them, and Gemini was receiving
  // potentially incomplete snapshots if they were undefined.
  queue_rate: number;
  num_failed: number;
  servers: ServerStatus[];
  run_id?: number;
  strategy?: string;
}

// Valid strategy names as a union type — single source of truth.
// Used in AgentDecision.strategy and anywhere else a strategy name
// is passed around, so TypeScript catches a bad name at compile time
// rather than letting it silently reach the backend.
export type StrategyName =
  | "baseline"
  | "random_backoff"
  | "consistent_hash"
  | "token_ring"
  | "leader_election";

export interface AgentDecision {
  // Tightened from `string` to the two valid literals — matches the enum
  // constraint added to responseSchema in geminiService.ts. TypeScript will
  // now flag any code path that tries to handle "start_run" or "stop_run"
  // (dead actions from the old prompt that were never handled downstream).
  action: "switch_strategy" | "explain";
  // Tightened from `string | null` to `StrategyName | null` — a hallucinated
  // strategy name from Gemini would now be caught here before the value
  // reaches the fetch to /switch-strategy.
  strategy: StrategyName | null;
  params: Record<string, unknown>;
  message: string;
}

// Comparison data types
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