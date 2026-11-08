import { Lock } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

const DIFFICULTY_STYLE: Record<string, string> = {
  easy: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200',
  hard: 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200',
}

export function CategoryBadge({ category }: { category: string }) {
  return <Badge variant="outline">{humanize(category)}</Badge>
}

export function DifficultyBadge({ difficulty }: { difficulty: string }) {
  return (
    <Badge className={cn('border-transparent', DIFFICULTY_STYLE[difficulty])}>
      {humanize(difficulty)}
    </Badge>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const variant = status === 'active' ? 'secondary' : 'outline'
  return (
    <Badge variant={variant} className={status === 'archived' ? 'text-muted-foreground' : ''}>
      {humanize(status)}
    </Badge>
  )
}

export function LockedBadge() {
  return (
    <Badge variant="outline" title="Used by a run: edits create a new version">
      <Lock aria-hidden /> Locked
    </Badge>
  )
}
