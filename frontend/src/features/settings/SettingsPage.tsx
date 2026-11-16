import { useQuery } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api, toApiError } from '@/lib/api'
import type { components } from '@/lib/api-schema'
import { humanize } from '@/lib/format'

/** Generated from the API schema (npm run gen:api). */
export type SettingsStatus = components['schemas']['SettingsStatusOut']

const LIMIT_LABELS: Record<string, string> = {
  llm_runs_per_day: 'LLM runs per day',
  judge_calls_per_day: 'Judge calls per day',
  concurrent_runs: 'Concurrent rule-based runs',
  concurrent_llm_runs: 'Concurrent LLM runs',
  queued_runs: 'Queued + running runs',
  run_launches_per_minute: 'Run launches per minute',
  request_body_bytes: 'Request body limit (bytes)',
}

function Rows({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Read-only view of how this server is configured. Keys are never shown, only whether one is set. */
export function SettingsPage() {
  const status = useQuery({
    queryKey: ['settings', 'status'],
    queryFn: async () => (await api.get<SettingsStatus>('/settings/status')).data,
  })
  if (status.isPending) return <Skeleton className="h-64 w-full" />
  if (status.isError) {
    return <Alert variant="destructive"><AlertDescription>{toApiError(status.error).message}</AlertDescription></Alert>
  }
  const s = status.data
  const used = s.usage_today
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          How this server is configured. Values come from environment variables on the server (see context/deployment.md);
          they are read-only here.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Gemini</CardTitle></CardHeader>
          <CardContent>
            <Rows rows={[
              ['API key', <span key="k" className="flex items-center gap-1"><KeyRound className="size-3.5" aria-hidden />
                {s.gemini.configured ? 'configured' : 'not configured'}</span>],
              ['Model', <span key="m" className="font-mono text-xs">{s.gemini.model}</span>],
              ['Thinking', s.gemini.thinking_level],
              ['Requests per minute', s.gemini.requests_per_minute],
              ['Request timeout', `${s.gemini.request_timeout_s} s`],
            ]} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2 text-base">LLM judge <Badge variant="outline">advisory</Badge></CardTitle></CardHeader>
          <CardContent>
            <Rows rows={[
              ['Status', s.judge.enabled ? 'enabled (owner can run it per run)' : 'off'],
              ['Model', <span key="m" className="font-mono text-xs">{s.judge.model}</span>],
              ['Prompt', <span key="p" className="font-mono text-xs">{s.judge.prompt_version}</span>],
            ]} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Limits</CardTitle></CardHeader>
          <CardContent>
            <Rows rows={Object.entries(s.limits).map(([k, v]) => {
              const today = k === 'llm_runs_per_day' ? used?.llm_runs : k === 'judge_calls_per_day' ? used?.judge_calls : undefined
              return [LIMIT_LABELS[k] ?? humanize(k), today === undefined ? v : `${v} (${today} used today)`]
            })} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Versions</CardTitle></CardHeader>
          <CardContent>
            <Rows rows={[
              ['App', `${s.app_version} (${s.environment})`],
              ...Object.entries(s.versions).map(([k, v]): [string, React.ReactNode] => [humanize(k), <span key={k} className="font-mono text-xs">{v}</span>]),
            ]} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
