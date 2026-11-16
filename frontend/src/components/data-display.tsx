import { FlaskRound } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

/** Marks seeded demo data (is_demo), so it is never mistaken for a real result. */
export function DemoBadge({ className }: { className?: string }) {
  return (
    <Badge variant="outline" className={cn('border-dashed text-muted-foreground', className)} title="Seeded demo data">
      <FlaskRound aria-hidden /> demo
    </Badge>
  )
}

/**
 * One row of a meter list: a horizontal bar (one hue, validated light #2a78d6 / dark #3987e5)
 * on a lighter track of the same hue, 8px thick, square at the baseline with a 4px rounded
 * data end, and its figure printed beside it in text ink. `value` is a fraction of `max`.
 */
export function MeterBar({ value, max = 1, label }: { value: number | null; max?: number; label: string }) {
  const pct = value === null || max <= 0 ? 0 : Math.max(0, Math.min(1, value / max)) * 100
  return (
    <div
      className="h-2 w-full overflow-hidden rounded-r-[4px] bg-[#2a78d6]/15 dark:bg-[#3987e5]/20"
      role="img"
      aria-label={label}
      title={label}
    >
      {value === null ? null : (
        <div className="h-full rounded-r-[4px] bg-[#2a78d6] dark:bg-[#3987e5]" style={{ width: `${pct}%` }} />
      )}
    </div>
  )
}

/** A meter-list row: name and figure on one line, the bar under them (fits narrow cards). */
export function MeterRow({
  name,
  figure,
  value,
  max = 1,
  label,
}: {
  name: string
  figure: React.ReactNode
  value: number | null
  max?: number
  label: string
}) {
  return (
    <li className="flex flex-col gap-1 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <span>{name}</span>
        <span className="tabular-nums text-muted-foreground">{figure}</span>
      </div>
      <MeterBar value={value} max={max} label={label} />
    </li>
  )
}
