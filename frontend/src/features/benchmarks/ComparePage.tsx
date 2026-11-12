import { ArrowLeft, ArrowRight, ShieldAlert } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { VerdictBadge } from '@/features/runs/VerdictBadge'
import { toApiError } from '@/lib/api'
import { formatDateTime, humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

import { useComparison, useSuiteRuns } from './api'
import { PairClassBadge } from './components'
import { formatMetric, METRIC_ROWS } from './format'
import type { Comparison, SuiteRun } from './types'

const CLASS_ORDER = ['newly_failed', 'fixed', 'still_failing', 'still_passing', 'not_comparable'] as const

function label(run: SuiteRun): string {
  return `${run.agent_name} v${run.agent_version} on ${run.suite_name} · ${formatDateTime(run.created_at)}`
}

function Delta({ value, better = 'up', unit = '' }: { value: number | null; better?: 'up' | 'down'; unit?: string }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>
  const good = better === 'up' ? value > 0 : value < 0
  return (
    <span className={cn('tabular-nums', value === 0 ? 'text-muted-foreground' : good ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400')}>
      {value > 0 ? '+' : ''}{Math.round(value * 100) / 100}{unit}
    </span>
  )
}

function Summary({ c }: { c: Comparison }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" aria-label="Comparison summary">
      {CLASS_ORDER.map((k) => (
        <Card key={k} className="gap-1 py-3">
          <CardContent className="flex flex-col gap-1 px-4">
            <PairClassBadge value={k} />
            <span className="text-2xl font-semibold tabular-nums">{c.counts[k]}</span>
          </CardContent>
        </Card>
      ))}
      <Card className={cn('gap-1 py-3', c.safety_regressions > 0 && 'border-rose-400')}>
        <CardContent className="flex flex-col gap-1 px-4">
          <span className="flex items-center gap-1 text-xs font-medium text-rose-700 dark:text-rose-400">
            <ShieldAlert className="size-3.5" aria-hidden /> Safety regressions
          </span>
          <span className="text-2xl font-semibold tabular-nums">{c.safety_regressions}</span>
        </CardContent>
      </Card>
    </div>
  )
}

const DOWN_IS_BETTER = new Set(['policy_violation_rate', 'infra_error_rate', 'mean_latency_ms', 'mean_tokens', 'estimated_cost_usd'])

export function ComparePage() {
  const [params, setParams] = useSearchParams()
  const baseline = params.get('baseline')
  const candidate = params.get('candidate')
  const runs = useSuiteRuns({ status: 'completed' })
  const comparison = useComparison(baseline, candidate)

  function pick(key: 'baseline' | 'candidate', value: string) {
    const next = new URLSearchParams(params)
    next.set(key, value)
    setParams(next)
  }

  const c = comparison.data
  return (
    <div className="flex flex-col gap-6">
      <Link to="/suites" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Benchmarks
      </Link>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Compare suite runs</h1>
        <p className="text-sm text-muted-foreground">
          Pairs scenarios by key and version and classifies each one. Computed from stored results only; nothing is re-run.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        {(['baseline', 'candidate'] as const).map((key, i) => (
          <div key={key} className="flex items-end gap-3">
            {i === 1 ? <ArrowRight className="mb-2.5 size-4 text-muted-foreground" aria-hidden /> : null}
            <div className="flex flex-col gap-1">
              <Label htmlFor={key} className="text-xs">{humanize(key)}</Label>
              <Select value={(key === 'baseline' ? baseline : candidate) ?? ''} onValueChange={(v) => pick(key, v)}>
                <SelectTrigger id={key} className="w-96"><SelectValue placeholder={`Choose the ${key} suite run`} /></SelectTrigger>
                <SelectContent>
                  {(runs.data ?? []).map((r) => <SelectItem key={r.id} value={r.id}>{label(r)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        ))}
      </div>

      {comparison.isError ? (
        <Alert variant="destructive"><AlertDescription>{toApiError(comparison.error).message}</AlertDescription></Alert>
      ) : null}
      {comparison.isFetching && !c ? <Skeleton className="h-40 w-full" /> : null}

      {c ? (
        <>
          {c.warnings.map((w) => <Alert key={w}><AlertDescription>{w}</AlertDescription></Alert>)}
          <Summary c={c} />
          <p className="text-sm text-muted-foreground">
            Regression rate:{' '}
            <span className="font-medium text-foreground">
              {c.regression_rate === null ? 'unknown (no comparable baseline passes)' : `${Math.round(c.regression_rate * 100)}%`}
            </span>{' '}
            of the scenarios the baseline passed.
          </p>

          <div className="rounded-lg border">
            <Table aria-label="Scenario pairs">
              <TableHeader>
                <TableRow>
                  <TableHead>Scenario</TableHead>
                  <TableHead>Change</TableHead>
                  <TableHead>Baseline</TableHead>
                  <TableHead>Candidate</TableHead>
                  <TableHead>Score Δ</TableHead>
                  <TableHead>Candidate&apos;s main finding</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...c.pairs]
                  .sort((a, b) => CLASS_ORDER.indexOf(a.pair_class) - CLASS_ORDER.indexOf(b.pair_class))
                  .map((p) => (
                    <TableRow key={p.scenario_key} className={cn(p.safety_regression && 'bg-rose-50 dark:bg-rose-950/30')}>
                      <TableCell className="font-mono text-xs">{p.scenario_key}</TableCell>
                      <TableCell>
                        <div className="flex flex-col items-start gap-1">
                          <PairClassBadge value={p.pair_class} />
                          {p.safety_regression ? (
                            <span className="flex items-center gap-1 text-xs text-rose-700 dark:text-rose-400">
                              <ShieldAlert className="size-3" aria-hidden /> safety regression: {p.new_gate_failures.join(', ')}
                            </span>
                          ) : null}
                          {p.reason ? <span className="text-xs text-muted-foreground">{p.reason}</span> : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        {p.baseline ? (
                          <Link to={`/runs/${p.baseline.run_ids[0]}`}><VerdictBadge verdict={p.baseline.verdict} /></Link>
                        ) : '—'}
                        {p.baseline?.flaky ? <span className="ml-1 text-xs text-amber-700">flaky</span> : null}
                      </TableCell>
                      <TableCell>
                        {p.candidate ? (
                          <Link to={`/runs/${p.candidate.run_ids[0]}`}><VerdictBadge verdict={p.candidate.verdict} /></Link>
                        ) : '—'}
                        {p.candidate?.flaky ? <span className="ml-1 text-xs text-amber-700">flaky</span> : null}
                      </TableCell>
                      <TableCell><Delta value={p.score_delta} /></TableCell>
                      <TableCell className="text-sm">{p.candidate?.main_failure ? humanize(p.candidate.main_failure) : '—'}</TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </div>

          <div className="rounded-lg border">
            <Table aria-label="Metric changes">
              <TableHeader>
                <TableRow>
                  <TableHead>Metric</TableHead>
                  <TableHead>Baseline</TableHead>
                  <TableHead>Candidate</TableHead>
                  <TableHead>Change</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {METRIC_ROWS.map((m) => {
                  const b = c.baseline.metrics?.[m.key] as number | null | undefined
                  const k = c.candidate.metrics?.[m.key] as number | null | undefined
                  const delta = c.metric_deltas[m.key] ?? null
                  const scale = m.kind === 'pct' ? 100 : m.kind === 'ms' ? 0.001 : 1
                  return (
                    <TableRow key={m.key}>
                      <TableCell>{m.label}</TableCell>
                      <TableCell className="tabular-nums">{formatMetric(m.kind, b)}</TableCell>
                      <TableCell className="tabular-nums">{formatMetric(m.kind, k)}</TableCell>
                      <TableCell>
                        <Delta value={delta === null ? null : delta * scale}
                               better={DOWN_IS_BETTER.has(m.key) ? 'down' : 'up'}
                               unit={m.kind === 'pct' ? ' pts' : m.kind === 'ms' ? ' s' : ''} />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </>
      ) : !baseline || !candidate ? (
        <Alert><AlertDescription>Choose a baseline and a candidate suite run to compare.</AlertDescription></Alert>
      ) : null}
    </div>
  )
}
