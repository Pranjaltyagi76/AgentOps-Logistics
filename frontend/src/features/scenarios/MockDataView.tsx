import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDate, formatDateTime, humanize } from '@/lib/format'

import type { MockData } from './types'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

function EvidenceId({ id }: { id: string }) {
  return <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{id}</code>
}

export function MockDataView({ data, asOf }: { data: MockData; asOf: string }) {
  const asOfTime = Date.parse(asOf)
  return (
    <div className="flex flex-col gap-4">
      {data.shipments.map((s) => (
        <Card key={s.shipment_id}>
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <CardTitle className="text-base">Shipment {s.shipment_id}</CardTitle>
            <EvidenceId id={`shipment:${s.shipment_id}`} />
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[max-content_1fr_max-content_1fr]">
              <Field label="Route">{s.origin_city} → {s.destination_city}</Field>
              <Field label="Service">{humanize(s.service_level)}</Field>
              <Field label="Status">{humanize(s.status)}</Field>
              <Field label="Carrier">{s.carrier_id ?? '—'}</Field>
              <Field label="Promised">{formatDate(s.promised_delivery_date)}</Field>
              <Field label="Current ETA">
                {formatDate(s.current_eta)} <span className="text-muted-foreground">({s.eta_status})</span>
              </Field>
              <Field label="Recipient">{s.recipient_name ?? '—'}</Field>
              <Field label="Attempts">
                {s.delivery_attempts}
                {s.next_attempt_date ? `, next ${formatDate(s.next_attempt_date)}` : ''}
              </Field>
            </dl>
          </CardContent>
        </Card>
      ))}

      {data.tracking_events.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tracking events</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Evidence ID</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead>Event</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.tracking_events.map((e) => {
                  const future = Date.parse(e.timestamp) > asOfTime
                  return (
                    <TableRow key={`${e.shipment_id}-${e.seq}`}>
                      <TableCell><EvidenceId id={`event:${e.shipment_id}:${String(e.seq).padStart(2, '0')}`} /></TableCell>
                      <TableCell className="whitespace-nowrap">
                        {formatDateTime(e.timestamp)}
                        {future ? <Badge variant="destructive" className="ml-2">after “now”</Badge> : null}
                      </TableCell>
                      <TableCell>{e.location}</TableCell>
                      <TableCell>
                        <span className="font-mono text-xs">{e.event_code}</span>
                        <p className="text-sm text-muted-foreground">{e.description}</p>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {data.carrier_status.map((c) => (
        <Card key={c.carrier_id}>
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <CardTitle className="text-base">
              {c.name} <span className="font-normal text-muted-foreground">({c.carrier_id})</span>
            </CardTitle>
            <EvidenceId id={`carrier:${c.carrier_id}`} />
          </CardHeader>
          <CardContent className="text-sm">
            <Badge variant={c.status === 'operational' ? 'secondary' : 'destructive'}>{humanize(c.status)}</Badge>
            <p className="mt-2">{c.notice ?? 'No active notice.'}</p>
            <p className="mt-1 text-xs text-muted-foreground">Updated {formatDateTime(c.updated_at)}</p>
          </CardContent>
        </Card>
      ))}

      {data.tickets.map((t) => (
        <Card key={t.ticket_id}>
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <CardTitle className="text-base">Ticket {t.ticket_id}: {t.subject}</CardTitle>
            <EvidenceId id={`ticket:${t.ticket_id}`} />
          </CardHeader>
          <CardContent className="text-sm">
            <p className="text-muted-foreground">
              {humanize(t.status)} · via {t.channel} · opened {formatDateTime(t.opened_at)}
              {t.shipment_id ? ` · shipment ${t.shipment_id}` : ''}
              {t.related_shipment_ids.length ? ` · related ${t.related_shipment_ids.join(', ')}` : ''}
            </p>
            {t.last_customer_message ? <p className="mt-2 italic">“{t.last_customer_message}”</p> : null}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
