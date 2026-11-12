import { CheckCircle2, CircleDashed, ShieldAlert, XCircle } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

import type { Evaluation, EvaluationAssertion } from './types'
import { VerdictBadge } from './VerdictBadge'

const COMPONENT_ORDER = ['root_cause', 'evidence', 'tool_correctness', 'policy', 'response_quality']
const GROUP_ORDER = [...COMPONENT_ORDER, 'escalation', 'consistency', 'run']

const VERDICT_TEXT: Record<string, string> = {
  PASS: 'The agent found the right cause, did what was required and scored above the threshold.',
  FAIL: 'The agent finished, but missed the cause, a required action or the score threshold.',
  FAILED_POLICY: 'A hard safety rule was broken. This fails the run whatever the score.',
  ERROR: 'A platform problem stopped this run. It is not counted against the agent.',
}

function show(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : 'none'
  return String(value)
}

export function TraceRefs({ refs }: { refs: string[] }) {
  if (!refs.length) return null
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {refs.map((ref) => (
        <a
          key={ref}
          href={`#${ref.replace(':', '-')}`}
          className="rounded bg-muted px-1 py-0.5 font-mono text-[11px] hover:bg-accent hover:underline"
        >
          {ref}
        </a>
      ))}
    </span>
  )
}

function AssertionRow({ a, owner }: { a: EvaluationAssertion; owner: boolean }) {
  const Icon = a.passed === null ? CircleDashed : a.passed ? CheckCircle2 : XCircle
  return (
    <li className="flex gap-2 py-1.5 text-sm">
      <Icon
        className={cn(
          'mt-0.5 size-4 shrink-0',
          a.passed === null ? 'text-muted-foreground' : a.passed ? 'text-emerald-600' : 'text-rose-600',
        )}
        aria-label={a.passed === null ? 'not applicable' : a.passed ? 'passed' : 'failed'}
      />
      <div className="min-w-0">
        <span className={cn(a.passed === false && 'font-medium')}>{a.summary}</span>
        {a.gate ? <Badge variant="outline" className="ml-1.5 border-rose-300 text-rose-700 dark:text-rose-300">gate</Badge> : null}
        {!a.weighted ? <span className="ml-1.5 text-xs text-muted-foreground">(not scored)</span> : null}
        <TraceRefs refs={a.cites} />
        <p className="font-mono text-xs text-muted-foreground">{a.id}</p>
        {owner && (a.expected !== null || (a.actual !== null && a.passed === false) || a.detail) ? (
          <p className="text-xs text-muted-foreground">
            {a.expected !== null ? <>expected <span className="text-foreground">{show(a.expected)}</span> · </> : null}
            actual <span className="text-foreground">{show(a.actual)}</span>
            {a.detail ? <> · {a.detail}</> : null}
          </p>
        ) : null}
      </div>
    </li>
  )
}

export function EvaluationPanel({ evaluation, owner }: { evaluation: Evaluation; owner: boolean }) {
  const e = evaluation
  const components = [...e.components].sort(
    (a, b) => COMPONENT_ORDER.indexOf(a.name) - COMPONENT_ORDER.indexOf(b.name),
  )
  const groups = GROUP_ORDER.map((name) => ({
    name,
    items: e.assertions.filter((a) => a.component === name),
  })).filter((g) => g.items.length)
  const failed = e.assertions.filter((a) => a.passed === false).length

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitle className="text-base">Evaluation</CardTitle>
          <p className="text-sm text-muted-foreground">{VERDICT_TEXT[e.verdict]}</p>
        </div>
        <div className="flex items-center gap-3">
          <VerdictBadge verdict={e.verdict} />
          {e.score !== null ? (
            <span className="text-2xl font-semibold tabular-nums">
              {e.score}
              <span className="text-sm font-normal text-muted-foreground"> / 100 (pass ≥ {e.pass_threshold})</span>
            </span>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {e.gate_failures.length ? (
          <Alert variant="destructive">
            <ShieldAlert aria-hidden />
            <AlertDescription>
              Safety gate{e.gate_failures.length === 1 ? '' : 's'} failed:{' '}
              <span className="font-mono">{e.gate_failures.join(', ')}</span>
            </AlertDescription>
          </Alert>
        ) : null}

        {components.length ? (
          <div className="flex flex-col gap-2.5" aria-label="Score components">
            {components.map((c) => {
              const pct = c.score === null ? 0 : Math.round(c.score * 100)
              return (
                <div key={c.name} className="grid grid-cols-[10rem_1fr_6rem] items-center gap-3 text-sm" title={c.detail}>
                  <span>
                    {humanize(c.name)} <span className="text-xs text-muted-foreground">×{c.weight}</span>
                  </span>
                  <div className="h-2 overflow-hidden rounded-full bg-muted" role="presentation">
                    <div
                      className={cn('h-full rounded-full', pct >= 100 ? 'bg-emerald-500' : pct > 0 ? 'bg-amber-500' : 'bg-rose-500')}
                      style={{ width: c.enabled ? `${pct}%` : '0%' }}
                    />
                  </div>
                  <span className="text-right tabular-nums text-muted-foreground">
                    {c.enabled ? `${pct}%` : 'not used'}
                  </span>
                </div>
              )
            })}
          </div>
        ) : null}

        <div>
          <h3 className="mb-1 text-sm font-medium">
            Checks <span className="font-normal text-muted-foreground">({failed} failed of {e.assertions.length})</span>
          </h3>
          {groups.map((g) => (
            <div key={g.name} className="border-t pt-2 first:border-t-0">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{humanize(g.name)}</p>
              <ul>{g.items.map((a) => <AssertionRow key={a.id} a={a} owner={owner} />)}</ul>
            </div>
          ))}
        </div>

        <p className="text-xs text-muted-foreground">
          Scored deterministically by {e.evaluator_version}.{' '}
          {e.shows_expected_values
            ? 'Expected values come from the hidden ground truth.'
            : 'Expected values are hidden for demo viewers, the same way the agent never sees them.'}{' '}
          Links like te:4 jump to the trace step that supports each check.
        </p>
      </CardContent>
    </Card>
  )
}
