import { Play } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toApiError } from '@/lib/api'
import { formatDateTime, humanize } from '@/lib/format'

import { useRuns } from './api'
import { RunStatusBadge } from './RunStatusBadge'
import { VerdictBadge } from './VerdictBadge'

const ALL = '__all__'
const STATUSES = ['queued', 'running', 'completed', 'timed_out', 'cancelled', 'errored']

export function RunListPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<string | undefined>(undefined)
  const runs = useRuns(status)
  const rows = runs.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
          <p className="text-sm text-muted-foreground">Every execution of an agent against a scenario, newest first.</p>
        </div>
        <Button size="sm" asChild>
          <Link to="/runs/new"><Play aria-hidden /> New run</Link>
        </Button>
      </header>

      <Select value={status ?? ALL} onValueChange={(v) => setStatus(v === ALL ? undefined : v)}>
        <SelectTrigger className="w-44" aria-label="Status filter"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All statuses</SelectItem>
          {STATUSES.map((s) => <SelectItem key={s} value={s}>{humanize(s)}</SelectItem>)}
        </SelectContent>
      </Select>

      {runs.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load runs</AlertTitle>
          <AlertDescription>{toApiError(runs.error).message}</AlertDescription>
        </Alert>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Created</TableHead>
                <TableHead>Scenario</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Verdict</TableHead>
                <TableHead className="text-right">Score</TableHead>
                <TableHead>Root cause given</TableHead>
                <TableHead className="text-right">Tool calls</TableHead>
                <TableHead className="text-right">Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.isPending
                ? Array.from({ length: 4 }, (_, i) => (
                    <TableRow key={i}><TableCell colSpan={9}><Skeleton className="h-8 w-full" /></TableCell></TableRow>
                  ))
                : rows.map((run) => (
                    <TableRow key={run.id} className="cursor-pointer" onClick={() => navigate(`/runs/${run.id}`)}>
                      <TableCell className="whitespace-nowrap">
                        <Link to={`/runs/${run.id}`} className="hover:underline" onClick={(e) => e.stopPropagation()}>
                          {formatDateTime(run.created_at)}
                        </Link>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{run.scenario_key} v{run.scenario_version}</TableCell>
                      <TableCell className="font-mono text-xs">{run.agent_name} v{run.agent_version}</TableCell>
                      <TableCell><RunStatusBadge status={run.status} /></TableCell>
                      <TableCell><VerdictBadge verdict={run.verdict} /></TableCell>
                      <TableCell className="text-right tabular-nums">{run.score ?? '—'}</TableCell>
                      <TableCell className="font-mono text-xs">{run.root_cause ?? '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{run.tool_call_count ?? '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {run.latency_ms !== null ? `${(run.latency_ms / 1000).toFixed(2)} s` : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
              {!runs.isPending && rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="py-10 text-center text-sm text-muted-foreground">
                    No runs yet. Start one with “New run”.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      )}
      {runs.hasNextPage ? (
        <Button variant="outline" className="self-center" onClick={() => void runs.fetchNextPage()} disabled={runs.isFetchingNextPage}>
          {runs.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </Button>
      ) : null}
    </div>
  )
}
