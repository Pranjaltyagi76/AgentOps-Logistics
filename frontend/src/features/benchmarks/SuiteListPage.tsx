import { GitCompareArrows, Pencil, Play, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAgents, useProviders } from '@/features/agents/api'
import type { ProviderStatus } from '@/features/agents/types'
import { toApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'

import { useLaunchSuite, useSuiteRuns, useSuites } from './api'
import { SuiteRunStatusBadge } from './components'
import { pct } from './format'
import type { Suite } from './types'

function LaunchForm({ suite }: { suite: Suite }) {
  const { isOwner } = useAuth()
  const navigate = useNavigate()
  const agents = useAgents()
  const providers = useProviders()
  const launch = useLaunchSuite(suite.id)
  const [agentId, setAgentId] = useState('')
  const [repeats, setRepeats] = useState('1')
  const [error, setError] = useState<string | null>(null)
  const status = new Map<string, ProviderStatus>((providers.data ?? []).map((p) => [p.provider, p]))
  const agent = agents.data?.find((a) => a.id === agentId)
  const llm = agent && agent.provider !== 'rule_based' ? status.get(agent.provider) : undefined
  const runs = suite.resolved.length * Number(repeats)

  function blocked(provider: string): string | null {
    if (provider === 'rule_based') return null
    if (!isOwner) return 'owner only'
    const p = status.get(provider)
    if (!p?.available) return 'not configured'
    return null
  }

  async function onLaunch() {
    setError(null)
    try {
      const run = await launch.mutateAsync({ agentId, repeats: Number(repeats) })
      navigate(`/suite-runs/${run.id}`)
    } catch (err) {
      setError(toApiError(err).message)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor={`agent-${suite.id}`} className="text-xs">Agent</Label>
          <Select value={agentId} onValueChange={setAgentId}>
            <SelectTrigger id={`agent-${suite.id}`} className="w-60"><SelectValue placeholder="Choose an agent" /></SelectTrigger>
            <SelectContent>
              {(agents.data ?? []).map((a) => {
                const reason = blocked(a.provider)
                return (
                  <SelectItem key={a.id} value={a.id} disabled={reason !== null}>
                    {a.name} v{a.version}{reason ? ` (${reason})` : ''}
                  </SelectItem>
                )
              })}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor={`repeats-${suite.id}`} className="text-xs">Repeats</Label>
          <Select value={repeats} onValueChange={setRepeats}>
            <SelectTrigger id={`repeats-${suite.id}`} className="w-24"><SelectValue /></SelectTrigger>
            <SelectContent>
              {['1', '2', '3'].map((r) => <SelectItem key={r} value={r}>{r}×</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <Button size="sm" disabled={!agentId || launch.isPending || !suite.resolved.length} onClick={() => void onLaunch()}>
          <Play aria-hidden /> {launch.isPending ? 'Starting…' : `Run ${runs} run${runs === 1 ? '' : 's'}`}
        </Button>
      </div>
      {llm ? (
        <p className="text-xs text-muted-foreground" data-testid="suite-llm-quota">
          Uses {runs} of today&apos;s {llm.daily_cap ?? '?'} LLM runs ({llm.runs_left_today ?? '?'} left). Gemini runs go one at
          a time within {llm.label}&apos;s request limit, so this can take several minutes.
        </p>
      ) : null}
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
    </div>
  )
}

export function SuiteListPage() {
  const { isOwner } = useAuth()
  const suites = useSuites()
  const runs = useSuiteRuns()

  if (suites.isPending) return <Skeleton className="h-64 w-full" />

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Benchmarks</h1>
          <p className="text-sm text-muted-foreground">
            Run one agent across a whole suite of scenarios, then compare two suite runs to see what was fixed and what broke.
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" asChild>
            <Link to="/compare"><GitCompareArrows aria-hidden /> Compare</Link>
          </Button>
          {isOwner ? (
            <Button size="sm" asChild>
              <Link to="/suites/new"><Plus aria-hidden /> New suite</Link>
            </Button>
          ) : null}
        </div>
      </header>

      {suites.isError ? (
        <Alert variant="destructive"><AlertDescription>{toApiError(suites.error).message}</AlertDescription></Alert>
      ) : (
        (suites.data ?? []).map((suite) => (
          <Card key={suite.id}>
            <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
              <div className="flex flex-col gap-1">
                <CardTitle className="text-base">{suite.title}</CardTitle>
                <p className="font-mono text-xs text-muted-foreground">
                  {suite.name} · {suite.tag ? `tag "${suite.tag}"` : 'explicit list'} · {suite.resolved.length} scenarios
                </p>
                {suite.description ? <p className="text-sm text-muted-foreground">{suite.description}</p> : null}
              </div>
              {isOwner ? (
                <Button size="sm" variant="ghost" asChild>
                  <Link to={`/suites/${suite.id}/edit`}><Pencil aria-hidden /> Edit</Link>
                </Button>
              ) : null}
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-1">
                {suite.resolved.map((s) => (
                  <Badge key={s.scenario_key} variant="secondary" className="font-mono text-[11px]">
                    {s.scenario_key} v{s.version}
                  </Badge>
                ))}
              </div>
              {suite.resolve_problem ? (
                <Alert variant="destructive"><AlertDescription>{suite.resolve_problem}</AlertDescription></Alert>
              ) : (
                <LaunchForm suite={suite} />
              )}
            </CardContent>
          </Card>
        ))
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Suite runs</h2>
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Suite</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Task success</TableHead>
                <TableHead>Policy violations</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(runs.data ?? []).map((r) => (
                <TableRow key={r.id}>
                  <TableCell>
                    <Link to={`/suite-runs/${r.id}`} className="hover:underline">{formatDateTime(r.created_at)}</Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{r.suite_name}</TableCell>
                  <TableCell className="font-mono text-xs">{r.agent_name} v{r.agent_version}{r.repeats > 1 ? ` · ${r.repeats}×` : ''}</TableCell>
                  <TableCell><SuiteRunStatusBadge status={r.status} /></TableCell>
                  <TableCell className="tabular-nums">{r.progress.done} / {r.total_runs}</TableCell>
                  <TableCell className="tabular-nums">{r.metrics ? pct(r.metrics.task_success_rate) : '—'}</TableCell>
                  <TableCell className="tabular-nums">{r.metrics ? pct(r.metrics.policy_violation_rate) : '—'}</TableCell>
                </TableRow>
              ))}
              {runs.data?.length === 0 ? (
                <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground">No suite runs yet.</TableCell></TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  )
}
