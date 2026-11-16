import { Loader2 } from 'lucide-react'

import { useSlowRequests } from '@/lib/slowRequests'

/** Shown while any API request has been waiting more than 5 s (free hosts cold-start). */
export function BackendWakingBanner() {
  const slow = useSlowRequests()
  if (slow === 0) return null
  return (
    <div role="status" className="flex items-center gap-2 border-b bg-amber-50 px-8 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      The backend is waking up (free hosting sleeps when idle). This can take up to a minute.
    </div>
  )
}
