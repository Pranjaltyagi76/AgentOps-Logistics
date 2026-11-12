import type { SuiteMetrics } from './types'

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? 'unknown' : `${Math.round(value * 1000) / 10}%`
}

export function num(value: number | null | undefined, unit = ''): string {
  if (value === null || value === undefined) return 'unknown'
  return `${Math.round(value * 10) / 10}${unit}`
}

export const METRIC_ROWS: { key: keyof SuiteMetrics; label: string; kind: 'pct' | 'ms' | 'num' }[] = [
  { key: 'task_success_rate', label: 'Task success', kind: 'pct' },
  { key: 'root_cause_accuracy', label: 'Root-cause accuracy', kind: 'pct' },
  { key: 'evidence_recall', label: 'Evidence recall', kind: 'pct' },
  { key: 'policy_violation_rate', label: 'Policy violations', kind: 'pct' },
  { key: 'escalation_recall', label: 'Escalation recall', kind: 'pct' },
  { key: 'escalation_precision', label: 'Escalation precision', kind: 'pct' },
  { key: 'tool_call_precision', label: 'Tool-call precision', kind: 'pct' },
  { key: 'infra_error_rate', label: 'Platform errors', kind: 'pct' },
  { key: 'mean_score', label: 'Mean score', kind: 'num' },
  { key: 'mean_latency_ms', label: 'Mean latency', kind: 'ms' },
  { key: 'mean_tokens', label: 'Tokens per run', kind: 'num' },
  { key: 'estimated_cost_usd', label: 'Cost', kind: 'num' },
]

export function formatMetric(kind: 'pct' | 'ms' | 'num', value: number | null | undefined): string {
  if (kind === 'pct') return pct(value)
  if (kind === 'ms') return value === null || value === undefined ? 'unknown' : `${(value / 1000).toFixed(2)} s`
  return num(value)
}

