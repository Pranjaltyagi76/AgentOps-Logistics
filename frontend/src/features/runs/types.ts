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
