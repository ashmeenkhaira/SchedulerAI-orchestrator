export interface ServerStatus {
  sid: number;
  busy: boolean;
  completed: number;
}

export interface MetricsPayload {
  time: number;
  queue_len: number;
  completed_total: number;
  fairness_std: number;
  servers: ServerStatus[];
  run_id?: number;
}

export interface AgentDecision {
  action: string;
  strategy: string | null;
  params: any;
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
