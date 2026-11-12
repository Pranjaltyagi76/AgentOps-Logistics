import { CheckCircle2, CircleDashed, KeyRound } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

import type { ProviderStatus } from './types'

const PROVIDER_LABEL: Record<string, string> = {
  rule_based: 'Rule-based',
  gemini: 'Gemini',
  openai: 'OpenAI',
}

export function ProviderBadge({ provider }: { provider: string }) {
  return (
    <Badge variant={provider === 'rule_based' ? 'secondary' : 'outline'}>
      {PROVIDER_LABEL[provider] ?? provider}
    </Badge>
  )
}

/** Shows whether each provider is usable. The server never sends keys, only "configured". */
export function ProviderStatusCards({ providers }: { providers: ProviderStatus[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {providers.map((p) => (
        <Card key={p.provider} className="gap-2 py-4">
          <CardHeader className="px-4">
            <CardTitle className="flex items-center justify-between gap-2 text-sm">
              {p.label}
              {p.available ? (
                <Badge className="bg-emerald-600 text-white">
                  <CheckCircle2 aria-hidden /> Available
                </Badge>
              ) : (
                <Badge variant="outline">
                  <CircleDashed aria-hidden /> {p.configured ? 'Not yet' : 'Not configured'}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-1 px-4 text-xs text-muted-foreground">
            {p.provider !== 'rule_based' ? (
              <span className="flex items-center gap-1">
                <KeyRound className="size-3" aria-hidden /> API key {p.configured ? 'configured' : 'not configured'}
              </span>
            ) : null}
            {p.available && p.runs_left_today != null && p.daily_cap != null ? (
              <span>
                {p.runs_left_today} of {p.daily_cap} LLM runs left today (resets 00:00 UTC)
              </span>
            ) : null}
            <span>{p.note}</span>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
