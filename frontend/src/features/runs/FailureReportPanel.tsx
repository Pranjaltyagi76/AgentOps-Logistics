import { CheckCircle2, Lightbulb, Stethoscope } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

import { TraceRefs } from './EvaluationPanel'
import type { FailureItem, FailureReport, Severity } from './types'

const SEVERITY_STYLE: Record<Severity, string> = {
  critical: 'border-transparent bg-rose-600 text-white',
  high: 'border-transparent bg-orange-500 text-white',
  medium: 'border-amber-300 text-amber-800 dark:text-amber-300',
  low: 'text-muted-foreground',
}

function Item({ item, owner }: { item: FailureItem; owner: boolean }) {
  return (
    <li
      className={cn('flex flex-col gap-1.5 rounded-lg border p-3', item.primary && 'border-foreground/30 bg-muted/40')}
      aria-label={`${item.severity} ${humanize(item.failure_type)}`}
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="outline" className={SEVERITY_STYLE[item.severity]}>{item.severity}</Badge>
        <span className="font-medium">{humanize(item.failure_type)}</span>
        <span className="text-xs text-muted-foreground">stage: {humanize(item.likely_stage)}</span>
        {item.primary ? <Badge variant="secondary">main finding</Badge> : null}
        <span className="ml-auto text-xs text-muted-foreground">confidence {item.confidence}</span>
      </div>
      <p className="text-sm">
        {item.summary}
        <TraceRefs refs={item.trace_refs} />
      </p>
      {owner && item.diagnosis ? <p className="text-sm text-muted-foreground">{item.diagnosis}</p> : null}
      <p className="flex gap-1.5 text-sm text-muted-foreground">
        <Lightbulb className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>{item.debugging_recommendation}</span>
      </p>
      <p className="font-mono text-xs text-muted-foreground">from {item.assertion_ids.join(', ')}</p>
    </li>
  )
}

export function FailureReportPanel({ report, owner }: { report: FailureReport; owner: boolean }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitle className="flex items-center gap-2 text-base">
            <Stethoscope className="size-4" aria-hidden /> Failure report
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            What went wrong, where in the agent&apos;s work, and the checks and trace steps that show it.
          </p>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {report.status === 'no_failures' ? (
          <p className="flex items-center gap-2 text-sm">
            <CheckCircle2 className="size-4 text-emerald-600" aria-hidden /> No failures found.
          </p>
        ) : report.status === 'not_diagnosed' ? (
          <p className="text-sm text-muted-foreground">
            A platform problem stopped this run, so there is nothing to diagnose about the agent.
          </p>
        ) : (
          <ol className="flex flex-col gap-2" aria-label="Failure items">
            {report.items.map((item) => <Item key={item.position} item={item} owner={owner} />)}
          </ol>
        )}
        <p className="text-xs text-muted-foreground">
          Rule-based diagnosis {report.diagnoser_version} of {report.evaluator_version}. It describes what the
          trace shows, not the model&apos;s hidden reasoning.
          {report.shows_details ? '' : ' Details that would reveal the expected answer are hidden for demo viewers.'}
        </p>
      </CardContent>
    </Card>
  )
}
