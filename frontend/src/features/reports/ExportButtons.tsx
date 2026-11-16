import { Download } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { downloadFile, toApiError } from '@/lib/api'

/** JSON and CSV downloads for a run or benchmark report (FR-10.2). */
export function ExportButtons({ path, basename }: { path: string; basename: string }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function download(format: 'json' | 'csv') {
    setBusy(format)
    setError(null)
    try {
      await downloadFile(path, { format }, `${basename}.${format}`)
    } catch (err) {
      setError(toApiError(err).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {(['json', 'csv'] as const).map((format) => (
        <Button key={format} variant="outline" size="sm" disabled={busy !== null} onClick={() => void download(format)}>
          <Download aria-hidden /> {busy === format ? 'Preparing…' : `Export ${format.toUpperCase()}`}
        </Button>
      ))}
      {error ? <span className="text-sm text-destructive">{error}</span> : null}
    </div>
  )
}
