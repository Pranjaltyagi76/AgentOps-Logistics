import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

import { formatMetric, METRIC_ROWS } from './format'
import type { PairClass, SuiteMetrics, SuiteRunStatus } from './types'

const STATUS_STYLE: Record<SuiteRunStatus, string> = {
  queued: 'text-muted-foreground',
  running: 'border-transparent bg-sky-600 text-white',
  completed: 'border-transparent bg-emerald-600 text-white',
  cancelled: 'text-muted-foreground',
}

export function SuiteRunStatusBadge({ status }: { status: SuiteRunStatus }) {
  return <Badge variant="outline" className={STATUS_STYLE[status]}>{humanize(status)}</Badge>
}

const CLASS_STYLE: Record<PairClass, string> = {
  fixed: 'border-transparent bg-emerald-600 text-white',
  newly_failed: 'border-transparent bg-rose-600 text-white',
  still_passing: 'border-emerald-300 text-emerald-700 dark:text-emerald-300',
  still_failing: 'border-amber-300 text-amber-800 dark:text-amber-300',
  not_comparable: 'text-muted-foreground',
}

export function PairClassBadge({ value }: { value: PairClass }) {
  return <Badge variant="outline" className={CLASS_STYLE[value]}>{humanize(value)}</Badge>
}

export function MetricCards({ metrics }: { metrics: SuiteMetrics }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-label="Suite metrics">
      {METRIC_ROWS.map((m) => {
        const value = metrics[m.key] as number | null
        return (
          <Card key={m.key} className="gap-1 py-3">
            <CardContent className="flex flex-col gap-0.5 px-4">
              <span className="text-xs text-muted-foreground">{m.label}</span>
              <span className={cn('text-xl font-semibold tabular-nums', value === null && 'text-base font-normal text-muted-foreground')}>
                {formatMetric(m.kind, value)}
              </span>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

