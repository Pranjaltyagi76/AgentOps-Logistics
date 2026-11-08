import { lazy, Suspense } from 'react'

import { Skeleton } from '@/components/ui/skeleton'

import { RequireOwner } from './auth/guards'

// The code editor is large; load it only when someone opens the editor.
const ScenarioEditorPage = lazy(() =>
  import('@/features/scenarios/ScenarioEditorPage').then((m) => ({ default: m.ScenarioEditorPage })),
)

export function EditorRoute({ mode }: { mode: 'create' | 'edit' }) {
  return (
    <RequireOwner>
      <Suspense fallback={<Skeleton className="h-[60vh] w-full" />}>
        <ScenarioEditorPage mode={mode} />
      </Suspense>
    </RequireOwner>
  )
}
