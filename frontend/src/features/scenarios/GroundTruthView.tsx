import { ShieldAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDate, humanize } from '@/lib/format'

import type { HiddenScenario, Taxonomy } from './types'

function Chips({ items, tone }: { items: string[]; tone?: 'danger' }) {
  if (!items.length) return <span className="text-muted-foreground">None</span>
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item) => (
        <Badge key={item} variant={tone === 'danger' ? 'destructive' : 'outline'} className="font-mono">
          {item}
        </Badge>
      ))}
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 py-2.5 sm:grid-cols-[13rem_1fr] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  )
}

export function GroundTruthView({ hidden, taxonomy }: { hidden: HiddenScenario; taxonomy?: Taxonomy }) {
  const gt = hidden.ground_truth
  const gates = new Set(taxonomy?.response_constraints.filter((c) => c.gate).map((c) => c.name))
  const rootInfo = taxonomy?.root_causes.find((r) => r.label === gt.root_cause)
  const weights = Object.entries(hidden.evaluation.weights)

  return (
    <div className="flex flex-col gap-4">
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <ShieldAlert className="size-4" aria-hidden /> Owner only. The agent under test never receives this.
      </p>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Expected outcome</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="divide-y">
            <Row label="Root cause">
              <span className="font-mono">{gt.root_cause}</span>
              {rootInfo ? <p className="text-muted-foreground">{rootInfo.description}</p> : null}
            </Row>
            <Row label="Escalation expected">{gt.expected_escalation ? 'Yes' : 'No'}</Row>
            <Row label="Supported ETA">{gt.supported_eta ? formatDate(gt.supported_eta) : 'None: no date may be quoted'}</Row>
            <Row label="Required evidence"><Chips items={gt.required_evidence} /></Row>
            <Row label="Required tools"><Chips items={gt.required_tools} /></Row>
            <Row label="Required actions"><Chips items={gt.required_actions} /></Row>
            <Row label="Forbidden actions"><Chips items={gt.forbidden_actions} tone="danger" /></Row>
            <Row label="Sequence constraints">
              {gt.sequence_constraints.length
                ? gt.sequence_constraints.map(([a, b]) => (
                    <p key={`${a}-${b}`} className="font-mono">{a} → before → {b}</p>
                  ))
                : <span className="text-muted-foreground">None</span>}
            </Row>
            <Row label="Response constraints">
              <div className="flex flex-wrap gap-1">
                {gt.response_constraints.map((c) => (
                  <Badge key={c} variant={gates.has(c) ? 'destructive' : 'outline'} className="font-mono">
                    {c}
                    {gates.has(c) ? ' · gate' : ''}
                  </Badge>
                ))}
              </div>
            </Row>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Scoring</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="divide-y">
            <Row label="Weights">
              <div className="flex flex-wrap gap-x-5 gap-y-1">
                {weights.map(([name, value]) => (
                  <span key={name}>{humanize(name)} <span className="font-semibold tabular-nums">{value}</span></span>
                ))}
              </div>
            </Row>
            <Row label="Pass threshold">{hidden.evaluation.pass_threshold} / 100</Row>
            <Row label="Judge rubric">{hidden.evaluation.rubric ?? <span className="text-muted-foreground">None</span>}</Row>
            <Row label="Fault injection">
              {hidden.fault_injection.length
                ? hidden.fault_injection.map((f) => (
                    <p key={f.tool} className="font-mono">
                      {f.tool}: {f.error}, {f.latency_ms} ms, calls {Array.isArray(f.calls) ? f.calls.join(', ') : f.calls}
                    </p>
                  ))
                : <span className="text-muted-foreground">None</span>}
            </Row>
            <Row label="Author note">{hidden.author_note ?? <span className="text-muted-foreground">None</span>}</Row>
          </dl>
        </CardContent>
      </Card>
    </div>
  )
}
