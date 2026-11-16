import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { DemoBadge, MeterRow } from '@/components/data-display'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useSuiteRuns } from '@/features/benchmarks/api'
import { MetricCards, SuiteRunStatusBadge } from '@/features/benchmarks/components'
import { pct } from '@/features/benchmarks/format'
import type { SuiteMetrics } from '@/features/benchmarks/types'
import { VerdictBadge } from '@/features/runs/VerdictBadge'
import { api, toApiError } from '@/lib/api'
import { formatDateTime, humanize } from '@/lib/format'

import { ExportButtons } from './ExportButtons'

interface BenchmarkReport {
  report_version: string
  shows_ground_truth_details: boolean
  suite_run: { id: string; suite_name: string; status: string; repeats: number; total_runs: number; is_demo: boolean;
    created_at: string; finished_at: string | null }
  agent: { name: string; version: number; provider: string }
  evaluator_versions: string[]
  metrics: SuiteMetrics | null
  flaky: string[]
  failure_counts: Record<string, number>
  runs: { run_id: string; scenario_key: string; scenario_version: number; repeat_index: number; status: string;
    verdict: string | null; score: number | null; gate_failures: string[]; main_failure: string | null;
    latency_ms: number | null }[]
}

/** List of benchmark runs to report on. */
export function ReportsPage() {
  const runs = useSuiteRuns()
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reports</h1>
        <p className="text-sm text-muted-foreground">
          Benchmark reports with every run ID and version needed to reproduce them, exportable as JSON or CSV.
          Single-run reports are on each run&apos;s page.
        </p>
      </div>
      {runs.isPending ? <Skeleton className="h-40 w-full" /> : null}
      {runs.isError ? <Alert variant="destructive"><AlertDescription>{toApiError(runs.error).message}</AlertDescription></Alert> : null}
      {runs.data ? (
        <div className="rounded-lg border">
          <Table aria-label="Benchmark runs">
            <TableHeader>
              <TableRow>
                <TableHead>Benchmark run</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Runs</TableHead>
                <TableHead>Task success</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.data.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>
                    <Link to={`/reports/${r.id}`} className="hover:underline">
                      {r.agent_name} v{r.agent_version} on {r.suite_name} · {formatDateTime(r.created_at)}
                    </Link>
                    {r.is_demo ? <DemoBadge className="ml-2" /> : null}
                  </TableCell>
                  <TableCell><SuiteRunStatusBadge status={r.status} /></TableCell>
                  <TableCell className="tabular-nums">{r.total_runs}</TableCell>
                  <TableCell className="tabular-nums">{r.metrics ? pct(r.metrics.task_success_rate) : '—'}</TableCell>
                </TableRow>
              ))}
              {runs.data.length === 0 ? (
                <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground">No benchmark runs yet: run a suite from Benchmarks.</TableCell></TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  )
}

/** One benchmark report: summary, scenario-by-scenario results, failure analysis, export. */
export function BenchmarkReportPage() {
  const { id = '' } = useParams()
  const report = useQuery({
    queryKey: ['reports', 'suite-run', id],
    queryFn: async () => (await api.get<BenchmarkReport>(`/reports/suite-runs/${id}`, { params: { format: 'json' } })).data,
  })
  if (report.isPending) return <Skeleton className="h-96 w-full" />
  if (report.isError) {
    return <Alert variant="destructive"><AlertDescription>{toApiError(report.error).message}</AlertDescription></Alert>
  }
  const r = report.data
  const failures = Object.entries(r.failure_counts)
  const failureMax = Math.max(1, ...failures.map(([, n]) => n))

  return (
    <div className="flex flex-col gap-6">
      <Link to="/reports" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Reports
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            {r.agent.name} v{r.agent.version} <span className="text-muted-foreground">on</span> {r.suite_run.suite_name}
          </h1>
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {r.suite_run.is_demo ? <DemoBadge /> : null}
            <span className="font-mono text-xs">{r.suite_run.id}</span>
            <span>· {r.suite_run.total_runs} runs · {r.evaluator_versions.join(', ') || 'not scored'} · {r.report_version}</span>
          </p>
        </div>
        <ExportButtons path={`/reports/suite-runs/${r.suite_run.id}`} basename={`benchmark-${r.suite_run.suite_name}-${r.suite_run.id}`} />
      </header>

      {r.metrics ? <MetricCards metrics={r.metrics} /> : <Alert><AlertDescription>Metrics appear once the benchmark run completes.</AlertDescription></Alert>}

      <Card>
        <CardHeader><CardTitle className="text-base">Failure analysis</CardTitle></CardHeader>
        <CardContent>
          {failures.length ? (
            <ul className="flex flex-col gap-3" aria-label="Failure counts">
              {failures.map(([type, n]) => (
                <MeterRow key={type} name={humanize(type)} figure={n} value={n} max={failureMax} label={`${humanize(type)}: ${n}`} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No failures found in this benchmark run.</p>
          )}
        </CardContent>
      </Card>

      <div className="rounded-lg border">
        <Table aria-label="Scenario results">
          <TableHeader>
            <TableRow>
              <TableHead>Scenario</TableHead>
              {r.suite_run.repeats > 1 ? <TableHead>Repeat</TableHead> : null}
              <TableHead>Verdict</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Safety gates failed</TableHead>
              <TableHead>Main finding</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {r.runs.map((x) => (
              <TableRow key={x.run_id}>
                <TableCell><Link to={`/runs/${x.run_id}`} className="font-mono text-xs hover:underline">{x.scenario_key} v{x.scenario_version}</Link></TableCell>
                {r.suite_run.repeats > 1 ? <TableCell className="tabular-nums">{x.repeat_index + 1}</TableCell> : null}
                <TableCell><VerdictBadge verdict={x.verdict} /></TableCell>
                <TableCell className="tabular-nums">{x.score ?? '—'}</TableCell>
                <TableCell className="font-mono text-xs">{x.gate_failures.join(', ') || '—'}</TableCell>
                <TableCell className="text-sm">{x.main_failure ? humanize(x.main_failure) : '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        {r.shows_ground_truth_details
          ? 'Exports include expected values and the detailed diagnosis (owner view).'
          : 'Exports leave out expected values and the detailed diagnosis, as on screen.'}
      </p>
    </div>
  )
}
