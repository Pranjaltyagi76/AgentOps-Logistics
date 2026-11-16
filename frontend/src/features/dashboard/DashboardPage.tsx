import { useQuery } from '@tanstack/react-query'
import { FlaskConical, Info, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { useAuth } from '@/app/auth/context'
import { DemoBadge, MeterBar, MeterRow } from '@/components/data-display'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { VerdictBadge } from '@/features/runs/VerdictBadge'
import { api, toApiError } from '@/lib/api'
import type { components } from '@/lib/api-schema'
import { formatDateTime, humanize } from '@/lib/format'

import { formatKpi } from './format'

type Dashboard = components['schemas']['DashboardOut']
type Kpi = components['schemas']['KpiOut']

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? 'unknown' : `${Math.round(value * 1000) / 10}%`
}

function KpiTile({ kpi }: { kpi: Kpi }) {
  const unknown = kpi.value === null || kpi.value === undefined
  return (
    <Card className="gap-1 py-3" title={`${kpi.definition}\n\n${kpi.sql}`}>
      <CardContent className="flex flex-col gap-0.5 px-4">
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          {kpi.label} <Info className="size-3" aria-label={kpi.definition} />
        </span>
        <span className={unknown ? 'text-base text-muted-foreground' : 'text-2xl font-semibold tabular-nums'}>
          {formatKpi(kpi)}
        </span>
      </CardContent>
    </Card>
  )
}

export function DashboardPage() {
  const { isOwner } = useAuth()
  const [includeDemo, setIncludeDemo] = useState(true)
  const query = useQuery({
    queryKey: ['dashboard', includeDemo],
    queryFn: async () =>
      (await api.get<Dashboard>('/dashboard/summary', { params: { include_demo: includeDemo } })).data,
  })

  if (query.isPending) return <Skeleton className="h-96 w-full" />
  if (query.isError) {
    return <Alert variant="destructive"><AlertDescription>{toApiError(query.error).message}</AlertDescription></Alert>
  }
  const d = query.data
  const failureMax = Math.max(1, ...d.failure_types.map((f) => f.items))
  const empty = d.kpis.find((k) => k.key === 'total_runs')?.value === 0

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Computed from stored runs only. Hover a figure to see its definition and SQL; platform errors are left out of every rate.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={includeDemo} onCheckedChange={(v) => setIncludeDemo(v === true)} aria-label="Include demo data" />
            Include demo data{d.demo_runs ? ` (${d.demo_runs} runs)` : ''}
          </label>
          <Button size="sm" variant="outline" asChild>
            <Link to="/suites"><FlaskConical aria-hidden /> Run a benchmark</Link>
          </Button>
          {isOwner ? (
            <Button size="sm" variant="outline" asChild>
              <Link to="/scenarios/new"><Plus aria-hidden /> New scenario</Link>
            </Button>
          ) : null}
        </div>
      </header>

      {includeDemo && d.demo_runs > 0 ? (
        <Alert>
          <AlertDescription className="flex items-center gap-2">
            <DemoBadge /> These figures include seeded demo runs (rule-based baselines), labelled wherever they appear.
          </AlertDescription>
        </Alert>
      ) : null}
      {empty ? (
        <Alert><AlertDescription>No runs yet. Launch a run or a benchmark suite and the figures fill in here.</AlertDescription></Alert>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" aria-label="Key figures">
        {d.kpis.map((kpi) => <KpiTile key={kpi.key} kpi={kpi} />)}
      </div>

      <div className="grid gap-4 2xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Most frequent failure types</CardTitle></CardHeader>
          <CardContent>
            {d.failure_types.length ? (
              <ul className="flex flex-col gap-3" aria-label="Failure types">
                {d.failure_types.map((f) => (
                  <MeterRow
                    key={f.failure_type}
                    name={humanize(f.failure_type)}
                    figure={<>{f.items} <span className="text-xs">({f.main_findings} main, {f.runs} runs)</span></>}
                    value={f.items}
                    max={failureMax}
                    label={`${humanize(f.failure_type)}: ${f.items} findings in ${f.runs} runs`}
                  />
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No failures recorded.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Agent versions</CardTitle></CardHeader>
          <CardContent>
            {d.agent_versions.length ? (
              <Table aria-label="Agent versions">
                <TableHeader>
                  <TableRow>
                    <TableHead>Agent</TableHead>
                    <TableHead>Runs</TableHead>
                    <TableHead className="w-40">Pass rate</TableHead>
                    <TableHead className="w-40">Policy violations</TableHead>
                    <TableHead>Mean score</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.agent_versions.map((a) => (
                    <TableRow key={`${a.agent_name}-${a.agent_version}`}>
                      <TableCell className="font-mono text-xs">{a.agent_name} v{a.agent_version}</TableCell>
                      <TableCell className="tabular-nums">{a.runs}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <MeterBar value={a.pass_rate} label={`Pass rate ${pct(a.pass_rate)}`} />
                          <span className="w-12 text-right text-xs tabular-nums">{pct(a.pass_rate)}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <MeterBar value={a.policy_violation_rate} label={`Policy violations ${pct(a.policy_violation_rate)}`} />
                          <span className="w-12 text-right text-xs tabular-nums">{pct(a.policy_violation_rate)}</span>
                        </div>
                      </TableCell>
                      <TableCell className="tabular-nums">{a.mean_score ?? 'unknown'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-sm text-muted-foreground">No scored runs yet.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Recent runs</CardTitle></CardHeader>
          <CardContent>
            <ul className="flex flex-col divide-y text-sm" aria-label="Recent runs">
              {d.recent_runs.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 py-1.5">
                  <Link to={`/runs/${r.id}`} className="font-mono text-xs hover:underline">{r.scenario_key}</Link>
                  <span className="text-xs text-muted-foreground">{r.agent_name} v{r.agent_version}</span>
                  {r.is_demo ? <DemoBadge /> : null}
                  <span className="ml-auto"><VerdictBadge verdict={r.verdict ?? null} /></span>
                </li>
              ))}
              {d.recent_runs.length === 0 ? <li className="py-1.5 text-muted-foreground">No runs yet.</li> : null}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Recent benchmark runs</CardTitle></CardHeader>
          <CardContent>
            <ul className="flex flex-col divide-y text-sm" aria-label="Recent benchmark runs">
              {d.recent_suite_runs.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center gap-2 py-1.5">
                  <Link to={`/suite-runs/${s.id}`} className="hover:underline">{s.agent_name} v{s.agent_version} on {s.suite_name}</Link>
                  {s.is_demo ? <DemoBadge /> : null}
                  <span className="text-xs text-muted-foreground">{formatDateTime(s.created_at)}</span>
                  <span className="ml-auto text-xs tabular-nums">task success {pct(s.task_success_rate)}</span>
                </li>
              ))}
              {d.recent_suite_runs.length === 0 ? <li className="py-1.5 text-muted-foreground">No benchmark runs yet.</li> : null}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
