// Mirrors backend/app/api/v1/runs.py.

export type RunStatus = 'queued' | 'running' | 'completed' | 'timed_out' | 'cancelled' | 'errored'

export const ACTIVE_STATUSES: RunStatus[] = ['queued', 'running']

export interface RunSummary {
  id: string
  status: RunStatus
  stop_reason: string | null
  scenario_id: string
  scenario_key: string
  scenario_version: number
  agent_config_id: string
  agent_name: string
  agent_version: number
  provider: string
  root_cause: string | null
  escalation: boolean | null
  tool_call_count: number | null
  latency_ms: number | null
  verdict: string | null
  score: number | null
  triggered_by_role: 'owner' | 'viewer'
  is_demo: boolean
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface RunOutcome {
  root_cause: string | null
  confidence: number | null
  evidence_ids: string[]
  action_summary: string[]
  escalation: boolean
  customer_response: string
  uncertainty_note: string | null
}

export interface RunDetail extends RunSummary {
  steps: number | null
  error_kind: 'agent' | 'infra' | null
  error: Record<string, unknown> | null
  outcome: RunOutcome | null
  actions: { id: string; kind: string; payload: Record<string, unknown> }[]
  usage: Record<string, unknown> | null
  limits: { max_steps: number; max_tool_calls: number; timeout_s: number }
  versions: Record<string, string | null>
  cancel_requested: boolean
  trace_event_count: number
}

export interface RunPage {
  items: RunSummary[]
  next_cursor: string | null
}

export type TraceEventType =
  | 'run_started'
  | 'agent_input'
  | 'agent_turn'
  | 'tool_result'
  | 'tool_error'
  | 'policy_denied'
  | 'outcome_submitted'
  | 'outcome_invalid'
  | 'limit_exceeded'
  | 'run_error'
  | 'run_finished'

export interface TraceEvent {
  seq: number
  ref: string
  event_type: TraceEventType | string
  node: string | null
  tool: string | null
  input: unknown
  output: unknown
  error: Record<string, unknown> | null
  evidence_ids: string[]
  duration_ms: number | null
  usage: Record<string, unknown> | null
  timestamp: string
}

export interface Trace {
  run_id: string
  status: RunStatus
  events: TraceEvent[]
}

export type Verdict = 'PASS' | 'FAIL' | 'FAILED_POLICY' | 'ERROR'

export interface EvaluationAssertion {
  id: string
  component: string
  passed: boolean | null
  summary: string
  gate: boolean
  weighted: boolean
  cites: string[]
  // Owner only (null for demo viewers): these reveal the hidden ground truth.
  expected: unknown
  actual: unknown
  detail: string | null
}

export interface EvaluationComponent {
  name: string
  weight: number
  score: number | null
  enabled: boolean
  detail: string
}

export interface Evaluation {
  run_id: string
  evaluator_version: string
  verdict: Verdict
  score: number | null
  task_success: boolean
  pass_threshold: number
  components: EvaluationComponent[]
  gate_failures: string[]
  assertions: EvaluationAssertion[]
  shows_expected_values: boolean
  created_at: string
  /** Advisory LLM judge result; never part of the score or verdict. */
  judge?: JudgeResult | null
  /** Owner only: the judge can be run on this server. */
  judge_available?: boolean
}

export interface JudgeResult {
  status: string
  advisory: boolean
  score: number
  uncertainty: 'low' | 'medium' | 'high'
  judge_model: string
  prompt_version: string
  created_at: string
  // Owner only
  rationale?: string
  evidence_refs?: string[]
  unknown_refs?: string[]
  served_model?: string
}

export type Severity = 'critical' | 'high' | 'medium' | 'low'

export interface FailureItem {
  position: number
  primary: boolean
  failure_type: string
  severity: Severity
  likely_stage: string
  confidence: 'high' | 'medium' | 'low'
  assertion_ids: string[]
  trace_refs: string[]
  summary: string
  debugging_recommendation: string
  // Owner only (null for demo viewers): may name the expected answer.
  diagnosis: string | null
  evidence: Record<string, unknown> | null
}

export interface FailureReport {
  run_id: string
  diagnoser_version: string | null
  evaluator_version: string
  verdict: Verdict
  status: 'diagnosed' | 'no_failures' | 'not_diagnosed'
  items: FailureItem[]
  shows_details: boolean
}
