import { CheckCircle2, CircleSlash, ShieldX, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

import type { Verdict } from './types'

const STYLE: Record<Verdict, { label: string; className: string; icon: typeof CheckCircle2 }> = {
  PASS: { label: 'Pass', className: 'bg-emerald-600 text-white', icon: CheckCircle2 },
  FAIL: { label: 'Fail', className: 'bg-amber-500 text-white', icon: XCircle },
  FAILED_POLICY: { label: 'Failed policy', className: 'bg-rose-600 text-white', icon: ShieldX },
  ERROR: { label: 'Not scored', className: 'bg-slate-500 text-white', icon: CircleSlash },
}

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return <span className="text-muted-foreground">—</span>
  const style = STYLE[verdict as Verdict] ?? STYLE.ERROR
  const Icon = style.icon
  return (
    <Badge className={cn('border-transparent', style.className)} title={verdict}>
      <Icon aria-hidden /> {style.label}
    </Badge>
  )
}
