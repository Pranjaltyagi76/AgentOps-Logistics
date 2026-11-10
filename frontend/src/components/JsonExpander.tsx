import { ChevronRight } from 'lucide-react'

/** Readable summary first; the raw JSON only on demand (UX requirement, PROJECT.md §16). */
export function JsonExpander({ value, label = 'Raw JSON' }: { value: unknown; label?: string }) {
  if (value === null || value === undefined) return null
  return (
    <details className="group mt-2 text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground">
        <ChevronRight className="size-3 transition-transform group-open:rotate-90" aria-hidden />
        {label}
      </summary>
      <pre className="mt-1 max-h-80 overflow-auto rounded-md border bg-muted/40 p-3 whitespace-pre-wrap break-all">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  )
}
