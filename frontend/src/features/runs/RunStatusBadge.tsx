import { Ban, CheckCircle2, Clock, Loader2, TimerOff, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

import type { RunStatus } from './types'

const STYLE: Record<RunStatus, { className: string; icon: typeof Clock; spin?: boolean }> = {
  queued: { className: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200', icon: Clock },
  running: { className: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200', icon: Loader2, spin: true },
  completed: { className: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200', icon: CheckCircle2 },
  timed_out: { className: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200', icon: TimerOff },
  cancelled: { className: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300', icon: Ban },
  errored: { className: 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200', icon: XCircle },
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const style = STYLE[status] ?? STYLE.errored
  const Icon = style.icon
  return (
    <Badge className={cn('border-transparent', style.className)}>
      <Icon className={cn(style.spin && 'animate-spin')} aria-hidden /> {humanize(status)}
    </Badge>
  )
}
