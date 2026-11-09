import { createBrowserRouter, Navigate } from 'react-router'

import { AgentDetailPage } from '@/features/agents/AgentDetailPage'
import { AgentListPage } from '@/features/agents/AgentListPage'
import { LoginPage } from '@/features/auth/LoginPage'
import { ScenarioDetailPage } from '@/features/scenarios/ScenarioDetailPage'
import { ScenarioListPage } from '@/features/scenarios/ScenarioListPage'
import { StatusPage } from '@/features/status/StatusPage'

import { RequireAuth } from './auth/guards'
import { AgentEditorRoute, EditorRoute } from './EditorRoute'
import { AppShell } from './layout/AppShell'
import { NotFoundPage } from './NotFoundPage'

export const routes = [
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/scenarios" replace /> },
      { path: 'scenarios', element: <ScenarioListPage /> },
      { path: 'scenarios/new', element: <EditorRoute mode="create" /> },
      { path: 'scenarios/:id', element: <ScenarioDetailPage /> },
      { path: 'scenarios/:id/edit', element: <EditorRoute mode="edit" /> },
      { path: 'agents', element: <AgentListPage /> },
      { path: 'agents/new', element: <AgentEditorRoute mode="create" /> },
      { path: 'agents/:id', element: <AgentDetailPage /> },
      { path: 'agents/:id/edit', element: <AgentEditorRoute mode="edit" /> },
      { path: 'status', element: <StatusPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
