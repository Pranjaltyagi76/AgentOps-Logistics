import type { Verdict } from '@/features/runs/types'

export interface ResolvedScenario {
  scenario_key: string
  version: number
  title: string
  category: string
}

export interface Suite {
  id: string
  name: string
  title: string
  description: string
  status: 'active' | 'archived'
  tag: string | null
  scenario_keys: string[] | null
  pinned_versions: Record<string, number>
  resolved: ResolvedScenario[]
  resolve_problem: string | null
  created_at: string
  updated_at: string
}

export interface SuiteIn {
  name: string
  title: string
  description: string
  scenario_keys?: string[] | null
  tag?: string | null
}

export interface SuiteMetrics {
  runs: number
  evaluated: number
  errors: number
  task_success_rate: number | null
  root_cause_accuracy: number | null
  evidence_recall: number | null
  tool_call_precision: number | null
  tool_call_success_rate: number | null
  policy_violation_rate: number | null
  escalation_precision: number | null
  escalation_recall: number | null
  infra_error_rate: number | null
  mean_latency_ms: number | null
  p95_latency_ms: number | null
  mean_steps: number | null
  mean_tool_calls: number | null
  mean_tokens: number | null
  estimated_cost_usd: number | null
  mean_score: number | null
  verdicts: Record<string, number>
}

export type SuiteRunStatus = 'queued' | 'running' | 'completed' | 'cancelled'

export interface SuiteRun {
  id: string
  suite_id: string
  suite_name: string
  agent_config_id: string
  agent_name: string
  agent_version: number
  provider: string
  status: SuiteRunStatus
  repeats: number
  total_runs: number
  progress: Record<string, number> & { done: number; active: number }
  scenarios: { scenario_key: string; version: number }[]
  evaluator_version: string | null
  metrics: SuiteMetrics | null
  flaky: string[]
  cancel_requested: boolean
  triggered_by_role: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface SuiteRunResult {
  run_id: string
  scenario_key: string
  scenario_version: number
  repeat_index: number
  status: string
  verdict: Verdict | null
  score: number | null
  gate_failures: string[]
  main_failure: string | null
  latency_ms: number | null
  tokens: number | null
}

export interface SuiteRunDetail extends SuiteRun {
  results: SuiteRunResult[]
}

export type PairClass = 'fixed' | 'newly_failed' | 'still_passing' | 'still_failing' | 'not_comparable'

export interface ScenarioSide {
  verdict: Verdict | null
  verdicts: Verdict[]
  flaky: boolean
  score: number | null
  gate_failures: string[]
  latency_ms: number | null
  tokens: number | null
  run_ids: string[]
  main_failure: string | null
}

export interface ComparisonPair {
  scenario_key: string
  pair_class: PairClass
  safety_regression: boolean
  reason: string | null
  baseline: ScenarioSide | null
  candidate: ScenarioSide | null
  score_delta: number | null
  latency_delta_ms: number | null
  tokens_delta: number | null
  new_gate_failures: string[]
}

export interface Comparison {
  baseline: SuiteRun
  candidate: SuiteRun
  pairs: ComparisonPair[]
  counts: Record<PairClass, number>
  safety_regressions: number
  regression_rate: number | null
  metric_deltas: Record<string, number | null>
  warnings: string[]
  version: string
}
