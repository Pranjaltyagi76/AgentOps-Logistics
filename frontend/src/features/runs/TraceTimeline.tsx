import {
  AlertTriangle,
  Bot,
  CircleStop,
  FileInput,
  Flag,
  Play,
  ShieldAlert,
  Wrench,
  XOctagon,
  type LucideIcon,
} from 'lucide-react'

import { JsonExpander } from '@/components/JsonExpander'
import { Badge } from '@/components/ui/badge'
import { humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

import type { TraceEvent } from './types'

type Tone = 'neutral' | 'tool' | 'warn' | 'danger' | 'success'

const META: Record<string, { label: string; icon: LucideIcon; tone: Tone }> = {
  run_started: { label: 'Run started', icon: Play, tone: 'neutral' },
  agent_input: { label: 'Agent input', icon: FileInput, tone: 'neutral' },
  agent_turn: { label: 'Agent turn', icon: Bot, tone: 'neutral' },
  tool_result: { label: 'Tool call', icon: Wrench, tone: 'tool' },
  tool_error: { label: 'Tool error', icon: AlertTriangle, tone: 'warn' },
  policy_denied: { label: 'Blocked by policy', icon: ShieldAlert, tone: 'danger' },
  outcome_submitted: { label: 'Outcome submitted', icon: Flag, tone: 'success' },
  outcome_invalid: { label: 'Invalid outcome', icon: AlertTriangle, tone: 'warn' },
  limit_exceeded: { label: 'Stopped', icon: CircleStop, tone: 'warn' },
  run_error: { label: 'Run error', icon: XOctagon, tone: 'danger' },
  run_finished: { label: 'Run finished', icon: Flag, tone: 'neutral' },
}

const TONE: Record<Tone, string> = {
  neutral: 'border-border',
  tool: 'border-sky-300 dark:border-sky-800',
  warn: 'border-amber-400 dark:border-amber-700',
  danger: 'border-rose-400 dark:border-rose-700',
  success: 'border-emerald-400 dark:border-emerald-700',
}

type Obj = Record<string, unknown>
const asObj = (v: unknown): Obj => (v && typeof v === 'object' ? (v as Obj) : {})

function Evidence({ ids }: { ids: string[] }) {
  if (!ids.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {ids.map((id) => (
        <code key={id} className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{id}</code>
      ))}
    </div>
  )
}

function Args({ value }: { value: unknown }) {
  const entries = Object.entries(asObj(value))
  if (!entries.length) return <span className="text-muted-foreground">(no arguments)</span>
  return (
    <span className="font-mono text-xs">
      {entries.map(([k, v], i) => (
        <span key={k}>
          {i ? ', ' : ''}
          {k}=<span className="text-foreground">{typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}</span>
        </span>
      ))}
    </span>
  )
}

function Body({ event }: { event: TraceEvent }) {
  const input = asObj(event.input)
  const output = asObj(event.output)
  const error = event.error ?? {}
  switch (event.event_type) {
    case 'run_started': {
      const scenario = asObj(output.scenario)
      const agent = asObj(output.agent)
      return (
        <p className="text-sm">
          <span className="font-mono">{String(agent.name)} v{String(agent.version)}</span> on{' '}
          <span className="font-mono">{String(scenario.key)} v{String(scenario.version)}</span>
        </p>
      )
    }
    case 'agent_input':
      return (
        <>
          <p className="text-sm">“{String(input.customer_message ?? '')}”</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Context {JSON.stringify(input.visible_context)} · now {String(input.now)} ·{' '}
            {Array.isArray(input.tools) ? input.tools.length : 0} tools ·{' '}
            {Array.isArray(input.root_cause_labels) ? input.root_cause_labels.length : 0} root-cause labels
          </p>
          <JsonExpander value={event.input} label="Exactly what the agent received" />
        </>
      )
    case 'agent_turn': {
      const calls = Array.isArray(output.tool_calls) ? (output.tool_calls as Obj[]) : []
      return (
        <>
          {output.text ? <p className="text-sm whitespace-pre-wrap">{String(output.text)}</p> : null}
          <ul className="flex flex-col gap-0.5 text-sm">
            {calls.map((call, i) => (
              <li key={i}>
                <span className="text-muted-foreground">→ </span>
                <span className="font-mono">{String(call.name)}</span>
                {call.name === 'submit_outcome' ? null : <> (<Args value={call.arguments} />)</>}
              </li>
            ))}
          </ul>
        </>
      )
    }
    case 'tool_result':
    case 'tool_error':
    case 'policy_denied':
      return (
        <>
          <p className="text-sm">
            <span className="font-mono font-medium">{event.tool}</span> (<Args value={input.arguments} />)
          </p>
          {event.event_type !== 'tool_result' ? (
            <p className="mt-1 text-sm">
              <Badge variant={event.event_type === 'policy_denied' ? 'destructive' : 'outline'} className="mr-1.5">
                {String(error.code)}
              </Badge>
              {String(error.message ?? '')}
              {asObj(error.details).rule_id ? (
                <span className="ml-1 font-mono text-xs text-muted-foreground">({String(asObj(error.details).rule_id)})</span>
              ) : null}
            </p>
          ) : null}
          {Number(input.simulated_latency_ms) > 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">Simulated latency {String(input.simulated_latency_ms)} ms</p>
          ) : null}
          <Evidence ids={event.evidence_ids} />
          <JsonExpander value={event.event_type === 'tool_result' ? event.output : event.error} label="Result" />
        </>
      )
    case 'outcome_submitted':
      return (
        <>
          <p className="text-sm">
            Root cause <span className="font-mono">{String(output.root_cause)}</span> · escalation{' '}
            {output.escalation ? 'yes' : 'no'}
          </p>
          <Evidence ids={event.evidence_ids} />
        </>
      )
    case 'outcome_invalid':
      return (
        <ul className="list-disc pl-4 text-sm">
          {(Array.isArray(error.problems) ? error.problems : []).map((p, i) => <li key={i}>{String(p)}</li>)}
        </ul>
      )
    case 'limit_exceeded':
      return <p className="text-sm">Reason: <span className="font-medium">{humanize(String(output.reason))}</span></p>
    case 'run_error':
      return <p className="text-sm"><span className="font-mono">{String(error.code)}</span> {String(error.message ?? '')}</p>
    case 'run_finished':
      return (
        <p className="text-sm">
          Status <span className="font-medium">{humanize(String(output.status))}</span>
          {output.stop_reason ? ` · stop reason ${humanize(String(output.stop_reason))}` : ''}
        </p>
      )
    default:
      return <JsonExpander value={{ input: event.input, output: event.output, error: event.error }} />
  }
}

export function TraceTimeline({ events }: { events: TraceEvent[] }) {
  if (!events.length) return <p className="text-sm text-muted-foreground">No trace events yet.</p>
  const start = Date.parse(events[0]!.timestamp)
  return (
    <ol className="flex flex-col gap-2" aria-label="Trace timeline">
      {events.map((event) => {
        const meta = META[event.event_type] ?? { label: humanize(event.event_type), icon: Flag, tone: 'neutral' as Tone }
        const Icon = meta.icon
        const offset = Date.parse(event.timestamp) - start
        return (
          <li
            key={event.seq}
            id={`te-${event.seq}`}
            className={cn(
              'scroll-mt-20 rounded-lg border border-l-4 bg-card p-3 target:ring-2 target:ring-primary',
              TONE[meta.tone],
            )}
          >
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">{event.ref}</code>
              <Icon className="size-3.5" aria-hidden />
              <span className="font-medium text-foreground">{meta.label}</span>
              {event.node ? <span>· {event.node}</span> : null}
              <span className="ml-auto tabular-nums">
                +{(offset / 1000).toFixed(2)} s{event.duration_ms !== null ? ` · ${event.duration_ms} ms` : ''}
              </span>
            </div>
            <div className="mt-1.5">
              <Body event={event} />
            </div>
          </li>
        )
      })}
    </ol>
  )
}
